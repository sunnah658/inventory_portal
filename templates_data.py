"""
templates_data.py - suggested starter columns for each department.

When the admin creates a department, the portal shows the matching list below as a
ticked checklist. The admin keeps what is useful and unticks the rest. Nothing here
is locked: every column can be edited or removed later in Admin > Departments.

Each entry is: (column name, type, dropdown options or None, is reminder date[, has time])
Types: text, longtext, number, date, dropdown, yesno
"""

STATUS = ["In use", "In stock", "Under repair", "Damaged", "Retired"]

TEMPLATES = {
    "IT": [
        ("Asset tag", "text", None, False), ("Equipment name", "text", None, False),
        ("Type", "dropdown", ["Desktop", "Laptop", "Monitor", "Printer", "Router", "Switch",
                              "Server", "Phone", "Other"], False),
        ("Brand", "text", None, False), ("Model", "text", None, False),
        ("Serial no", "text", None, False), ("Assigned to", "text", None, False),
        ("Location", "text", None, False), ("IP address", "text", None, False),
        ("MAC address", "text", None, False), ("Operating system", "text", None, False),
        ("Purchase date", "date", None, False), ("Warranty end date", "date", None, True),
        ("Status", "dropdown", STATUS, False), ("Remarks", "longtext", None, False),
    ],
    "HR & Admin": [
        ("Employee name", "text", None, False), ("Employee ID", "text", None, False),
        ("Designation", "text", None, False), ("Joining date", "date", None, False),
        ("Item issued", "text", None, False), ("Issue date", "date", None, False),
        ("Return date", "date", None, False), ("Office supply item", "text", None, False),
        ("Quantity", "number", None, False), ("Contract end date", "date", None, True),
        ("Remarks", "longtext", None, False),
    ],
    "Billing & Revenue": [
        ("Invoice no.", "text", None, False), ("Client", "text", None, False),
        ("Invoice date", "date", None, False), ("Due date", "date", None, True),
        ("Amount", "number", None, False),
        ("Currency", "dropdown", ["BDT", "USD", "EUR", "GBP"], False),
        ("Payment status", "dropdown", ["Paid", "Unpaid", "Partial", "Overdue"], False),
        ("Payment method", "dropdown", ["Cash", "Bank transfer", "Card", "Mobile banking",
                                        "Cheque"], False),
        ("Receipt no.", "text", None, False), ("Remarks", "longtext", None, False),
    ],
    "Sales & Marketing": [
        ("Client or lead", "text", None, False), ("Contact person", "text", None, False),
        ("Phone", "text", None, False), ("Email", "text", None, False),
        ("Campaign", "text", None, False),
        ("Deal stage", "dropdown", ["Lead", "Contacted", "Proposal", "Negotiation", "Won",
                                    "Lost"], False),
        ("Expected value", "number", None, False), ("Follow-up date", "date", None, True),
        ("Meeting", "date", None, True, True),
        ("Assigned to", "text", None, False), ("Marketing material", "text", None, False),
        ("Remarks", "longtext", None, False),
    ],
    "Technical": [
        ("System or equipment name", "text", None, False), ("Type", "text", None, False),
        ("Serial no", "text", None, False), ("Site or location", "text", None, False),
        ("Installation date", "date", None, False), ("Last maintenance date", "date", None, False),
        ("Next maintenance date", "date", None, True), ("Vendor", "text", None, False),
        ("Warranty end date", "date", None, False), ("Status", "dropdown", STATUS, False),
        ("Remarks", "longtext", None, False),
    ],
    "Accounts": [
        ("Asset tag", "text", None, False), ("Equipment name", "text", None, False),
        ("Invoice no.", "text", None, False), ("Voucher no.", "text", None, False),
        ("Cost centre", "text", None, False), ("Vendor", "text", None, False),
        ("Purchase date", "date", None, False), ("Purchase cost", "number", None, False),
        ("Payment status", "dropdown", ["Paid", "Unpaid", "Partial"], False),
        ("Warranty months", "number", None, False), ("Remarks", "longtext", None, False),
    ],
    "Management": [
        ("Title", "text", None, False), ("Responsible person", "text", None, False),
        ("Budget", "number", None, False),
        ("Priority", "dropdown", ["Low", "Medium", "High", "Critical"], False),
        ("Approval status", "dropdown", ["Pending", "Approved", "Rejected"], False),
        ("Approved by", "text", None, False), ("Approval date", "date", None, False),
        ("Review date", "date", None, True), ("Remarks", "longtext", None, False),
    ],
}

# Short names that also pick a template (used by the CSV user import).
_ALIASES = {"it": "IT", "hr": "HR & Admin", "admin": "HR & Admin", "hr & admin": "HR & Admin",
            "billing": "Billing & Revenue", "revenue": "Billing & Revenue",
            "sales": "Sales & Marketing", "marketing": "Sales & Marketing",
            "technical": "Technical", "accounts": "Accounts", "management": "Management"}


def match_template(department_name):
    """Return the template key that fits a department name, or None."""
    name = (department_name or "").strip().lower()
    for key in TEMPLATES:
        if key.lower() == name:
            return key
    return _ALIASES.get(name)
