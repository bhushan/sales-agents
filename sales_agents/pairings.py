"""The six seller/target pairings from the workshop's final project, offered
as a shortcut so nobody has to retype them. Picking one is optional."""

import sys

from . import ui

# (You sell for, What they sell, Target account)
PAIRINGS = [
    ("MoveInSync", "Employee commute and fleet software", "Mphasis"),
    ("Xoxoday", "Sales commission and incentive software", "Bajaj Finserv"),
    ("WebEngage", "Customer engagement and retention platform", "Honasa (Mamaearth)"),
    ("IDfy", "Identity verification and background checks", "Poonawalla Fincorp"),
    ("GoKwik", "Checkout and return-to-origin technology", "boAt"),
    ("TrueFoundry", "Platform for deploying machine learning models", "Meesho"),
]


def as_values(index: int) -> dict:
    seller, offering, company = PAIRINGS[index]
    return {"seller": seller, "offering": offering, "company": company}


def choose(*, input_fn=input, out=None):
    """Returns the chosen pairing's values, or None to answer by hand."""
    out = out or sys.stdout
    out.write("\n  " + ui.dim("Workshop pairings") + "\n")
    for number, (seller, offering, company) in enumerate(PAIRINGS, start=1):
        out.write(
            "    "
            + ui.cyan(str(number))
            + "  "
            + ui.pad(ui.bold(seller) + ui.dim(" → ") + company, 42)
            + ui.dim(offering)
            + "\n"
        )
    out.flush()

    def validate(value):
        if not value.isdigit() or not 1 <= int(value) <= len(PAIRINGS):
            return f"pick a number between 1 and {len(PAIRINGS)}, or press enter"
        return None

    answer = ui.ask(
        "Pick a pairing",
        hint="or press enter to describe your own",
        required=False,
        validate=validate,
        input_fn=input_fn,
        out=out,
    )
    return as_values(int(answer) - 1) if answer else None
