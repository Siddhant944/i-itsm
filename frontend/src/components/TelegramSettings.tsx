import { useState, type SyntheticEvent } from "react";

import { useTelegramLink } from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { Button } from "./Button";
import { TextField } from "./Field";
import { Modal } from "./Modal";
import { useToasts } from "./Toasts";

/**
 * §5.4, P4.9: where someone's critical and high-priority alerts go on Telegram. The chat ID is
 * a number; a bot can only write to people who have started a chat with it.
 */
export function TelegramSettings({ onClose }: { onClose: () => void }) {
  const { user } = useAuth();
  const toasts = useToasts();
  const { link, unlink, test } = useTelegramLink();
  const [chatId, setChatId] = useState("");
  if (user === null) return null;
  const linked = user.telegram_chat_id ?? null;

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    if (chatId.trim() === "") return;
    link.mutate(chatId.trim(), {
      onSuccess: () => {
        toasts.success("Telegram linked. Critical and high-priority alerts will go there.");
        setChatId("");
      },
      onError: (error) => {
        toasts.error(error);
      },
    });
  };

  return (
    <Modal title="Telegram alerts" onClose={onClose}>
      <div className="space-y-4 text-sm">
        <p className="text-muted">
          Critical (P1) and high (P2) incidents can also reach you on Telegram. Start a chat with
          the I-ITSM bot, then ask @userinfobot for your chat ID and enter it here.
        </p>
        {!user.telegram_available && (
          <p role="status" className="rounded-md border border-line bg-raised px-3 py-2 text-xs">
            This deployment has no Telegram bot set up yet. Your chat ID is kept for when it does.
          </p>
        )}
        {linked !== null ? (
          <div className="flex flex-wrap items-center gap-2" data-testid="telegram-linked">
            <span>
              Alerts go to chat <strong className="font-mono">{linked}</strong>.
            </span>
            <Button
              small
              busy={test.isPending}
              disabled={!user.telegram_available}
              onClick={() => {
                test.mutate(undefined, {
                  onSuccess: () => {
                    toasts.success("Test message sent. Check Telegram.");
                  },
                  onError: (error) => {
                    toasts.error(error);
                  },
                });
              }}
            >
              Send a test
            </Button>
            <Button
              small
              busy={unlink.isPending}
              onClick={() => {
                unlink.mutate(undefined, {
                  onSuccess: () => {
                    toasts.success("Telegram unlinked.");
                  },
                  onError: (error) => {
                    toasts.error(error);
                  },
                });
              }}
            >
              Unlink
            </Button>
          </div>
        ) : (
          <form className="flex flex-wrap items-end gap-2" onSubmit={submit} noValidate>
            <div className="min-w-48 flex-1">
              <TextField
                label="Telegram chat ID"
                inputMode="numeric"
                value={chatId}
                onChange={(event) => {
                  setChatId(event.target.value);
                }}
              />
            </div>
            <Button
              type="submit"
              variant="primary"
              busy={link.isPending}
              disabled={chatId.trim() === ""}
            >
              Link
            </Button>
          </form>
        )}
      </div>
    </Modal>
  );
}
