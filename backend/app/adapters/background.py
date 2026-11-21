"""Deliver email and chat messages on a background thread (D-043).

Pattern: Decorator. Problem solved: an SMTP hand-off (connect, STARTTLS, log in, send) or a
Telegram Bot API call takes one to three seconds, a P1 report sends several messages, and the
notification service retries a failed send, so delivering them inside the request kept the
person who pressed Submit waiting for every one of them. These wrappers keep the senders'
ports, queue each ``send()`` and return at once; one worker thread delivers the queue in order.
The in-app notification, the audit record and the live push are unaffected: they never left
the request. A delivery that fails on the worker is logged with its channel and recipient, so
the notification's status records the hand-off to the queue rather than the final delivery.
"""

import logging
import queue
import threading
from collections.abc import Callable

from app.domain.ports import ChatSender, EmailSender

logger = logging.getLogger(__name__)

Job = Callable[[], None]


class DeliveryWorker:
    """One daemon thread that runs queued deliveries in the order they were queued."""

    def __init__(self) -> None:
        self.__jobs: queue.Queue[tuple[str, str, Job]] = queue.Queue()
        self.__lock = threading.Lock()
        self.__thread: threading.Thread | None = None

    def submit(self, channel: str, recipient: str, job: Job) -> None:
        """Queue ``job``; the first submission starts the thread."""
        with self.__lock:
            if self.__thread is None:
                self.__thread = threading.Thread(
                    target=self.__run, name="notification-delivery", daemon=True
                )
                self.__thread.start()
        self.__jobs.put((channel, recipient, job))

    def drain(self, timeout: float = 5.0) -> bool:
        """Wait until every queued delivery has run (tests and shutdown); True if it did."""
        done = threading.Event()
        self.__jobs.put(("", "", done.set))
        with self.__lock:
            started = self.__thread is not None
        return done.wait(timeout) if started else True

    def __run(self) -> None:
        while True:
            channel, recipient, job = self.__jobs.get()
            try:
                job()
            except Exception:
                logger.exception("background %s delivery to %s failed", channel, recipient)
            finally:
                self.__jobs.task_done()


class BackgroundEmailSender(EmailSender):
    """An EmailSender that hands each message to the worker and returns at once."""

    def __init__(self, inner: EmailSender, worker: DeliveryWorker) -> None:
        self.__inner = inner
        self.__worker = worker
        self.name = inner.name

    def send(self, to: str, subject: str, body: str) -> None:
        self.__worker.submit(self.name, to, lambda: self.__inner.send(to, subject, body))


class BackgroundChatSender(ChatSender):
    """A ChatSender that hands each message to the worker and returns at once."""

    def __init__(self, inner: ChatSender, worker: DeliveryWorker) -> None:
        self.__inner = inner
        self.__worker = worker
        self.name = inner.name

    def send(self, chat_id: str, text: str) -> None:
        self.__worker.submit(self.name, chat_id, lambda: self.__inner.send(chat_id, text))
