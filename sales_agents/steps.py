import re
from dataclasses import dataclass, field
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"
CONTEXT_DIR = Path(__file__).parent / "context"

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


class TemplateRenderError(KeyError):
    pass


def render(template: str, values: dict) -> str:
    def _sub(match: "re.Match") -> str:
        key = match.group(1)
        if key not in values:
            raise TemplateRenderError(f"Missing template value: {{{{{key}}}}}")
        return values[key]

    return _PLACEHOLDER_RE.sub(_sub, template)


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    template: str
    output_name: str
    produces: str
    requires: tuple = field(default_factory=tuple)


STEP_ORDER = [
    "icp",
    "industry",
    "account",
    "roles",
    "people",
    "pack",
    "grade_research",
    "emails_a",
    "emails_b",
    "linkedin",
    "grade_messages",
]

STEPS = {
    step.id: step
    for step in [
        Step(
            id="icp",
            title="Step 0 — Who should Procol sell to?",
            template="00_icp.md",
            output_name="00-icp.md",
            produces="icp",
            requires=("our_product",),
        ),
        Step(
            id="industry",
            title="Step 1 — What is changing in their industry?",
            template="01_industry.md",
            output_name="01-industry.md",
            produces="industry_output",
            requires=("our_product", "icp", "industry"),
        ),
        Step(
            id="account",
            title="Step 2 — Account research",
            template="02_account.md",
            output_name="02-account.md",
            produces="account_output",
            requires=("industry_output", "company"),
        ),
        Step(
            id="roles",
            title="Step 3 — Who would be involved",
            template="03_roles.md",
            output_name="03-roles.md",
            produces="roles_output",
            requires=("account_output", "company"),
        ),
        Step(
            id="people",
            title="Step 4 — Real named people",
            template="04_people.md",
            output_name="04-people.md",
            produces="people_output",
            requires=("roles_output", "company"),
        ),
        Step(
            id="pack",
            title="Assemble the personalization pack",
            template="05_pack.md",
            output_name="05-personalization-pack.md",
            produces="pack_output",
            requires=(
                "icp",
                "industry_output",
                "account_output",
                "roles_output",
                "people_output",
                "company",
                "group",
                "date",
            ),
        ),
        Step(
            id="grade_research",
            title="Grade the research",
            template="06_grade_research.md",
            output_name="06-grade-research.md",
            produces="grade_output",
            requires=("pack_output",),
        ),
        Step(
            id="emails_a",
            title="Emails — Style A (open with the industry change)",
            template="07a_emails_style_a.md",
            output_name="07a-emails-style-a.md",
            produces="emails_a_output",
            requires=("pack_output",),
        ),
        Step(
            id="emails_b",
            title="Emails — Style B (open with what the person said/did)",
            template="07b_emails_style_b.md",
            output_name="07b-emails-style-b.md",
            produces="emails_b_output",
            requires=("pack_output",),
        ),
        Step(
            id="linkedin",
            title="LinkedIn outreach",
            template="08_linkedin.md",
            output_name="08-linkedin.md",
            produces="linkedin_output",
            requires=("pack_output",),
        ),
        Step(
            id="grade_messages",
            title="Grade the messages",
            template="09_grade_messages.md",
            output_name="09-grade-messages.md",
            produces="grade_messages_output",
            requires=("pack_output", "messages_output"),
        ),
    ]
}


def load_template(step: Step) -> str:
    return (PROMPTS_DIR / step.template).read_text()
