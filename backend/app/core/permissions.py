"""Permission catalogue and the seeded role presets.

Permissions are rows in the database; this module is the source of truth for
what gets seeded. Adding a role later is data, not a code change."""
from __future__ import annotations

PERMISSIONS: dict[str, str] = {
    "dashboard.view": "See the company-wide dashboard",
    "shop.read": "View shops",
    "shop.manage": "Create and edit shops and cities",
    "accounting.read": "View daily accounting records",
    "accounting.create": "Create daily accounting records",
    "accounting.update": "Edit daily accounting records",
    "accounting.delete": "Delete (archive) daily accounting records",
    "accounting.lock": "Lock a record against further edits",
    "bank.manage": "Create and edit banks and bank accounts",
    "statement.read": "View bank statements",
    "statement.upload": "Upload bank statement PDFs",
    "statement.delete": "Archive bank statements",
    "transaction.read": "View extracted bank transactions",
    "reconciliation.read": "View reconciliation results",
    "reconciliation.match": "Confirm or create matches",
    "reconciliation.unmatch": "Undo a match",
    "report.read": "View reports",
    "report.export": "Export reports to Excel or PDF",
    "audit.read": "View the audit log",
    "user.manage": "Create and edit users and roles",
    "settings.manage": "Change system and matching settings",
}

ALL_PERMISSIONS = sorted(PERMISSIONS)

SHOP_USER_PERMISSIONS = [
    "shop.read",
    "accounting.read",
    "accounting.create",
    "accounting.update",
    "reconciliation.read",
    "report.read",
]

ACCOUNTANT_PERMISSIONS = [
    "shop.read",
    "accounting.read",
    "accounting.create",
    "accounting.update",
    "statement.read",
    "statement.upload",
    "transaction.read",
    "reconciliation.read",
    "reconciliation.match",
    "reconciliation.unmatch",
    "report.read",
    "report.export",
    "dashboard.view",
]

ROLE_PRESETS: dict[str, dict] = {
    "ADMIN": {
        "name": "Administrator",
        "description": "Full access to every shop, bank and setting.",
        "permissions": ALL_PERMISSIONS,
    },
    "ACCOUNTANT": {
        "name": "Accountant",
        "description": "Works across all shops and banks but cannot manage users.",
        "permissions": ACCOUNTANT_PERMISSIONS,
    },
    "SHOP_USER": {
        "name": "Shop user",
        "description": "Enters the daily sheet for their assigned shops only.",
        "permissions": SHOP_USER_PERMISSIONS,
    },
}

# Roles that see every shop regardless of user_shops assignments.
GLOBAL_SCOPE_PERMISSION = "dashboard.view"
