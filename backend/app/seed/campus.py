"""The campus catalogue the demo starts from (blueprint §9: ``seed.py`` creates the services).

Everything here is plain data an administrator could type into the UI instead: skills,
categories with their classifier keywords, services with criticality and dependencies, and the
support teams. The dependency edges are what the correlation engine walks in §6.2, so the Fee
Payment Portal really does depend on the database cluster.
"""

from dataclasses import dataclass, field

from app.domain.catalogue import FALLBACK_TEAM_NAME
from app.domain.priority import Priority

SKILLS: tuple[str, ...] = (
    "networking",
    "database",
    "windows",
    "linux",
    "email",
    "identity",
    "printing",
    "web",
    "hardware",
    "security",
)


@dataclass(frozen=True, slots=True)
class CategorySeed:
    name: str
    skill: str
    keywords: tuple[str, ...]
    minimum_priority: Priority | None = None


CATEGORIES: tuple[CategorySeed, ...] = (
    CategorySeed(
        "Network", "networking", ("wifi", "network", "internet", "connection", "dns", "slow")
    ),
    CategorySeed(
        "Account and Access", "identity", ("password", "login", "sso", "locked", "account", "mfa")
    ),
    CategorySeed("Email", "email", ("email", "mailbox", "outlook", "spam", "attachment")),
    CategorySeed("Software", "windows", ("install", "software", "licence", "application", "crash")),
    CategorySeed("Hardware", "hardware", ("laptop", "keyboard", "monitor", "battery", "dock")),
    CategorySeed("Printing", "printing", ("printer", "print", "toner", "scan", "queue")),
    CategorySeed("Web Application", "web", ("portal", "website", "page", "timeout", "error")),
    CategorySeed("Database", "database", ("database", "query", "report", "data", "backup")),
    CategorySeed(
        "Security",
        "security",
        ("phishing", "virus", "malware", "breach", "suspicious"),
        Priority.P2,
    ),
    CategorySeed(
        "Payments", "web", ("fee", "payment", "transaction", "receipt", "refund"), Priority.P2
    ),
)


@dataclass(frozen=True, slots=True)
class ServiceSeed:
    name: str
    criticality: int
    skill: str | None = None
    depends_on: tuple[str, ...] = field(default_factory=tuple)


SERVICES: tuple[ServiceSeed, ...] = (
    ServiceSeed("Campus Network Core", 3, "networking"),
    ServiceSeed("Database Cluster", 3, "database"),
    ServiceSeed("Identity Provider", 3, "identity"),
    ServiceSeed("Campus Email", 2, "email", ("Identity Provider", "Campus Network Core")),
    ServiceSeed(
        "Fee Payment Portal",
        3,
        "web",
        ("Database Cluster", "Identity Provider", "Campus Network Core"),
    ),
    ServiceSeed("Student Information System", 3, "web", ("Database Cluster", "Identity Provider")),
    ServiceSeed("Exam Portal", 3, "web", ("Database Cluster", "Identity Provider")),
    ServiceSeed(
        "Learning Management System",
        2,
        "web",
        ("Database Cluster", "Identity Provider", "Campus Network Core"),
    ),
    ServiceSeed("Library Portal", 2, "web", ("Database Cluster", "Identity Provider")),
    ServiceSeed("Campus Wi-Fi", 2, "networking", ("Campus Network Core",)),
    ServiceSeed("VPN", 2, "networking", ("Identity Provider", "Campus Network Core")),
    ServiceSeed("Hostel Management", 1, "database", ("Database Cluster",)),
    ServiceSeed("Printing Service", 1, "printing", ("Campus Network Core",)),
    ServiceSeed("Lab Workstations", 1, "windows", ("Campus Network Core",)),
)

# D-004: the team an unassigned incident falls back to. The name lives in the domain, because
# the escalation fallback looks the team up by it.
SERVICE_DESK = FALLBACK_TEAM_NAME
TEAMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (SERVICE_DESK, ("windows", "hardware", "printing")),
    ("Network Operations", ("networking",)),
    ("Systems and Database", ("database", "linux", "web")),
    ("Identity and Email", ("identity", "email")),
    ("Security Operations", ("security",)),
)
