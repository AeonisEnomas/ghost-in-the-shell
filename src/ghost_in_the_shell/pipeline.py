"""From a plain-English request to a checked, previewed command.

    request
      -> clean          remove control tokens and hidden characters
      -> relevance      is it a shell task? does it try to instruct the model?
      -> generate       fine-tuned model, one line
      -> validate       bash syntax, programs installed, right distribution
                        (on failure, up to two more samples are tried)
      -> assess         risk level and reasons
      -> preview        dry run in the sandbox, over a throwaway layer of the folder

Nothing runs for real until the user confirms, and the rules for that are
enforced here, not only in the interface: commands are re-assessed before
running, commands that need administrator rights are refused, and dangerous
ones need a typed confirmation.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from . import context, sandbox
from .model import Explanation, ModelError, Models
from .relevance import Relevance, RelevanceChecker
from .safety import Assessment, Level, assess
from .sanitize import InputRejected, check_command, clean_request, manipulation_signs

CONFIRM_WORD = "run"
RETRY_SEEDS = (1, 2)
RETRY_TEMPERATURE = 0.7


class RunRefused(Exception):
    """The command may not be run from the app. The message is shown to the user."""


@dataclass(frozen=True)
class Review:
    """Everything known about a command before it runs."""
    command: str
    issues: tuple[str, ...]
    assessment: Assessment
    preview: sandbox.Preview

    @property
    def runnable(self) -> bool:
        return not self.assessment.elevated and not any(i.startswith("Syntax") for i in self.issues)


@dataclass(frozen=True)
class Outcome:
    status: Literal["ok", "rejected", "off_topic", "error"]
    request: str
    message: str = ""
    relevance: Relevance | None = None
    review: Review | None = None
    attempts: int = 0
    generation_seconds: float = 0.0
    alternatives: tuple[str, ...] = field(default=())


def validation_issues(command: str, assessment: Assessment) -> tuple[str, ...]:
    issues = []
    error = context.syntax_error(command)
    if error:
        issues.append(f"Syntax error: {error}")
    checkable = tuple(p for p in assessment.programs if "$" not in p and "`" not in p)
    hints = context.distro_hints(checkable)
    issues += hints
    hinted = {h.split()[0] for h in hints}
    for program in context.missing_programs(checkable):
        if program not in hinted:
            issues.append(f"{program} is not installed on this system.")
    return tuple(issues)


class Assistant:
    def __init__(self, models: Models, relevance: RelevanceChecker | None):
        self.models = models
        self.relevance = relevance

    def review(self, command: str, cwd: Path) -> Review:
        """Validate, assess and preview a command, from the model or typed by the user."""
        command = check_command(command)
        assessment = assess(command, cwd)
        issues = validation_issues(command, assessment)
        preview = sandbox.preview(command, cwd, elevated=assessment.elevated)
        return Review(command, issues, assessment, preview)

    def ask(self, request: str, cwd: Path, force: bool = False) -> Outcome:
        """Turn a request into a reviewed command.

        With force=False, requests that do not look like shell tasks, or that
        try to instruct the model, stop with status "off_topic" so the user
        can decide whether to continue.
        """
        signs = manipulation_signs(request)
        try:
            request = clean_request(request)
        except InputRejected as error:
            return Outcome("rejected", request, str(error))
        if signs and not force:
            return Outcome("off_topic", request, f"This request contains {signs}, which are used to "
                           "manipulate assistants. They have been removed.", None)

        relevance = self.relevance.check(request) if self.relevance else None
        if relevance and not force:
            if relevance.injection_phrases:
                return Outcome("off_topic", request, "This request seems to give instructions to the "
                               "assistant rather than describe a task.", relevance)
            if not relevance.on_topic:
                return Outcome("off_topic", request, "This doesn't look like a task for the command line.",
                               relevance)

        start = time.perf_counter()
        try:
            candidates = [self.models.suggest(request).command]
            command = candidates[0]
            assessment = assess(command, cwd)
            issues = validation_issues(command, assessment)
            for seed in RETRY_SEEDS:
                if not issues:
                    break
                other = self.models.suggest(request, temperature=RETRY_TEMPERATURE, seed=seed).command
                if other in candidates:
                    continue
                candidates.append(other)
                other_assessment = assess(other, cwd)
                other_issues = validation_issues(other, other_assessment)
                if not other_issues:
                    command, assessment, issues = other, other_assessment, other_issues
        except (ModelError, InputRejected) as error:
            return Outcome("error", request, str(error), relevance)
        seconds = time.perf_counter() - start

        preview = sandbox.preview(command, cwd, elevated=assessment.elevated)
        review = Review(command, issues, assessment, preview)
        alternatives = tuple(c for c in candidates if c != command)
        return Outcome("ok", request, "", relevance, review, len(candidates), seconds, alternatives)

    def explain(self, command: str) -> Explanation:
        return self.models.explain(command)

    def run(self, command: str, cwd: Path, confirmation: str = "") -> sandbox.RunResult:
        """Run a command for real. Re-checks it rather than trusting the caller."""
        command = check_command(command)
        assessment = assess(command, cwd)
        if assessment.elevated:
            raise RunRefused("Commands that need administrator rights are not run from the app. "
                             "Copy it into your own terminal if you are sure.")
        if context.syntax_error(command):
            raise RunRefused("The command has a syntax error.")
        if assessment.level is Level.DANGER and confirmation.strip().lower() != CONFIRM_WORD:
            raise RunRefused(f'This command is dangerous. Type "{CONFIRM_WORD}" to confirm.')
        return sandbox.run(command, cwd)
