"""Synthetic campus registries, thesis repositories and bank accounts."""

from __future__ import annotations

STUDENTS: dict[str, list[dict[str, object]]] = {
    "harbor": [
        {
            "id": "H2021001",
            "name": "Ada Lin",
            "enroll_year": "2021",
            "graduation_year": "2025",
            "gpa": 3.82,
        },
        {
            "id": "H2021002",
            "name": "Ben Okafor",
            "enroll_year": "2021",
            "graduation_year": "2025",
            "gpa": 3.41,
        },
        {
            "id": "H2022003",
            "name": "Chen Yu",
            "enroll_year": "2022",
            "graduation_year": "2026",
            "gpa": 3.67,
        },
        {
            "id": "H2022004",
            "name": "Dana Ruiz",
            "enroll_year": "2022",
            "graduation_year": "2026",
            "gpa": 2.95,
        },
        {
            "id": "H2023005",
            "name": "Eli Novak",
            "enroll_year": "2023",
            "graduation_year": "2027",
            "gpa": 3.58,
        },
    ],
    "summit": [
        {
            "id": "S2020011",
            "name": "Farah Haddad",
            "enroll_year": "2020",
            "graduation_year": "2024",
            "gpa": 3.91,
        },
        {
            "id": "S2021012",
            "name": "Gus Moreau",
            "enroll_year": "2021",
            "graduation_year": "2025",
            "gpa": 3.12,
        },
        {
            "id": "S2022013",
            "name": "Hana Sato",
            "enroll_year": "2022",
            "graduation_year": "2026",
            "gpa": 3.74,
        },
    ],
}

THESES: dict[str, list[dict[str, str]]] = {
    "harbor": [
        {
            "title": "Federated Learning for Privacy-Preserving Learning Analytics",
            "abstract": "Trains dropout predictors across three campuses without moving student records.",
            "author": "Ada Lin",
            "year": "2025",
        },
        {
            "title": "Policy-Aware Data Spaces for Higher Education",
            "abstract": "Maps the IDS reference architecture onto cross-university data exchange.",
            "author": "Ben Okafor",
            "year": "2025",
        },
        {
            "title": "Graph Neural Networks for Course Prerequisite Discovery",
            "abstract": "Recovers prerequisite structure from enrolment sequences of 40k students.",
            "author": "Chen Yu",
            "year": "2026",
        },
    ],
    "summit": [
        {
            "title": "Tamper-Evident Audit Logs with Hash Chains",
            "abstract": "Compares hash chains and Merkle trees for append-only institutional logs.",
            "author": "Farah Haddad",
            "year": "2024",
        },
        {
            "title": "Learning Analytics Dashboards and Student Self-Regulation",
            "abstract": "A semester-long field study of dashboard use in first-year programming.",
            "author": "Hana Sato",
            "year": "2026",
        },
    ],
}

# bank -> account number -> account
ACCOUNTS: list[dict[str, object]] = [
    {
        "bank": "E-DBA Bank",
        "name": "E-DBA account",
        "number": "596117071864958",
        "password": "edba123",
        "balance": 0.0,
    },
    {
        "bank": "FutureLearn Federal Bank",
        "name": "Utopia Credit Union",
        "number": "670547811218584",
        "password": "9978",
        "balance": 50_000.0,
    },
    {
        "bank": "Global Education Bank",
        "name": "Campus Cash Cooperative",
        "number": "641387141765274",
        "password": "8799",
        "balance": 20_000.0,
    },
    {
        "bank": "Pearl River Savings",
        "name": "Lakeside Scholars Fund",
        "number": "622848000123456",
        "password": "4321",
        "balance": 300.0,
    },
]
