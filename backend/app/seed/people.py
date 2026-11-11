"""The demo accounts and the support staff.

One account per role so a reviewer can sign in as each portal (blueprint §14), plus the
technicians the assignment strategies choose between and the employees who report the
historical incidents. Everything is fixed data, so ids and emails are the same on every machine.
"""

from dataclasses import dataclass, field

from app.domain.permissions import Role

DEMO_PASSWORD = "demo1234"  # noqa: S105 - the documented demo password, never a real secret


@dataclass(frozen=True, slots=True)
class UserSeed:
    user_id: int
    email: str
    full_name: str
    role: Role
    skills: tuple[str, ...] = field(default_factory=tuple)
    experience_level: int = 1
    team: str | None = None
    available: bool = True


# --- the five demo accounts (ids 1-5)
DEMO_USERS: tuple[UserSeed, ...] = (
    UserSeed(1, "employee@campus.edu", "Devika Rao", Role.EMPLOYEE),
    UserSeed(
        2,
        "technician@campus.edu",
        "Arjun Menon",
        Role.TECHNICIAN,
        ("networking", "windows"),
        2,
        "Network Operations",
    ),
    UserSeed(
        3,
        "lead@campus.edu",
        "Priya Nair",
        Role.TEAM_LEAD,
        ("networking", "database", "linux"),
        3,
        "Network Operations",
    ),
    UserSeed(4, "admin@campus.edu", "Rahul Verma", Role.ADMINISTRATOR),
    UserSeed(5, "manager@campus.edu", "Sunita Iyer", Role.IT_MANAGER),
)

# --- the rest of the support staff (ids 6-20); each team has a lead
TECHNICIANS: tuple[UserSeed, ...] = (
    UserSeed(
        6,
        "s.desk1@campus.edu",
        "Kavya Pillai",
        Role.TEAM_LEAD,
        ("windows", "hardware"),
        3,
        "Service Desk",
    ),
    UserSeed(
        7,
        "s.desk2@campus.edu",
        "Imran Shaikh",
        Role.TECHNICIAN,
        ("windows", "printing"),
        1,
        "Service Desk",
    ),
    UserSeed(
        8,
        "s.desk3@campus.edu",
        "Neha Gupta",
        Role.TECHNICIAN,
        ("hardware", "printing"),
        2,
        "Service Desk",
    ),
    UserSeed(
        9,
        "s.desk4@campus.edu",
        "Vikram Das",
        Role.TECHNICIAN,
        ("windows", "hardware", "printing"),
        2,
        "Service Desk",
    ),
    UserSeed(
        10,
        "net1@campus.edu",
        "Farhan Qureshi",
        Role.TECHNICIAN,
        ("networking",),
        3,
        "Network Operations",
    ),
    UserSeed(
        11,
        "net2@campus.edu",
        "Ananya Bose",
        Role.TECHNICIAN,
        ("networking", "linux"),
        2,
        "Network Operations",
    ),
    UserSeed(
        12,
        "sys1@campus.edu",
        "Rohit Khanna",
        Role.TEAM_LEAD,
        ("database", "linux", "web"),
        3,
        "Systems and Database",
    ),
    UserSeed(
        13,
        "sys2@campus.edu",
        "Meera Joshi",
        Role.TECHNICIAN,
        ("database", "web"),
        3,
        "Systems and Database",
    ),
    UserSeed(
        14,
        "sys3@campus.edu",
        "Aditya Reddy",
        Role.TECHNICIAN,
        ("linux", "web"),
        2,
        "Systems and Database",
    ),
    UserSeed(
        15,
        "sys4@campus.edu",
        "Tara Sheikh",
        Role.TECHNICIAN,
        ("database",),
        1,
        "Systems and Database",
        available=False,
    ),
    UserSeed(
        16,
        "id1@campus.edu",
        "Nikhil Chandra",
        Role.TEAM_LEAD,
        ("identity", "email"),
        3,
        "Identity and Email",
    ),
    UserSeed(
        17,
        "id2@campus.edu",
        "Pooja Malhotra",
        Role.TECHNICIAN,
        ("identity",),
        2,
        "Identity and Email",
    ),
    UserSeed(
        18, "id3@campus.edu", "Sameer Dutta", Role.TECHNICIAN, ("email",), 1, "Identity and Email"
    ),
    UserSeed(
        19,
        "sec1@campus.edu",
        "Lakshmi Krishnan",
        Role.TEAM_LEAD,
        ("security", "linux"),
        3,
        "Security Operations",
    ),
    UserSeed(
        20,
        "sec2@campus.edu",
        "Omar Baig",
        Role.TECHNICIAN,
        ("security", "networking"),
        2,
        "Security Operations",
    ),
)

ADMINS: tuple[UserSeed, ...] = (
    UserSeed(21, "it.ops@campus.edu", "Harish Kumar", Role.ADMINISTRATOR),
)

_EMPLOYEE_NAMES: tuple[str, ...] = (
    "Aarav Sharma",
    "Diya Patel",
    "Ishaan Singh",
    "Myra Agarwal",
    "Kabir Jain",
    "Anika Chopra",
    "Reyansh Mishra",
    "Saanvi Kulkarni",
    "Vivaan Ghosh",
    "Aadhya Bhat",
    "Advik Rawat",
    "Kiara Sethi",
    "Dhruv Trivedi",
    "Navya Menon",
    "Arnav Saxena",
    "Pari Deshmukh",
    "Atharv Rane",
    "Avni Shetty",
    "Ayaan Hussain",
    "Riya Kapoor",
    "Shaurya Bhatia",
    "Aanya Kaul",
    "Veer Chauhan",
    "Ira Vaidya",
    "Rudra Pandey",
    "Zara Ahmed",
    "Yash Thakur",
    "Mahi Bansal",
    "Krish Goel",
    "Siya Mehta",
)


#: Reporters are ids 100 and up, so staff ids stay stable when the list grows.
def _email(full_name: str) -> str:
    first, last = full_name.lower().split()
    return f"{first}.{last}@campus.edu"


EMPLOYEES: tuple[UserSeed, ...] = tuple(
    UserSeed(100 + index, _email(name), name, Role.EMPLOYEE)
    for index, name in enumerate(_EMPLOYEE_NAMES)
)

ALL_USERS: tuple[UserSeed, ...] = DEMO_USERS + TECHNICIANS + ADMINS + EMPLOYEES
