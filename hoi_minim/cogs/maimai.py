import decimal
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, override

from discord.ext import commands
from discord.ext.commands import Context
from z3 import Int, Or, RealVal, Solver, ToInt, unknown, unsat

if TYPE_CHECKING:
    from hoi_minim.bot import MinimBot
    from hoi_minim.cogs.allowlister import AllowlisterCog

MAX_BASE_SCORE = Decimal("100")
MAX_BREAK_BONUS = Decimal("1")

HOLD_PER_TAP = 2
SLIDE_PER_TAP = 3
BREAK_PER_TAP = 5

GREAT_PER_TAP = Decimal("0.8")
GOOD_PER_TAP = Decimal("0.5")

HIGH_GREAT_BREAK_PER_TAP = GREAT_PER_TAP * BREAK_PER_TAP
MID_GREAT_BREAK_PER_TAP = Decimal("0.6") * BREAK_PER_TAP
LOW_GREAT_BREAK_PER_TAP = Decimal("0.5") * BREAK_PER_TAP
GOOD_BREAK_PER_TAP = Decimal("0.4") * BREAK_PER_TAP

BREAK_2550_BONUS = Decimal("0.75")
BREAK_2500_BONUS = Decimal("0.5")
GREAT_BREAK_BONUS = Decimal("0.4")
GOOD_BREAK_BONUS = Decimal("0.3")

RE_JUDGEMENT_DETAILS = re.compile(
    r"TAP:\s+(?P<tap_pcrit>\d+)?\s+(?P<tap_perfect>\d+)?\s+(?P<tap_great>\d+)?\s+(?P<tap_good>\d+)?\s+(?P<tap_miss>\d+)?\n"
    r"HOLD:\s+(?P<hold_pcrit>\d+)?\s+(?P<hold_perfect>\d+)?\s+(?P<hold_great>\d+)?\s+(?P<hold_good>\d+)?\s+(?P<hold_miss>\d+)?\n"
    r"SLIDE:\s+(?P<slide_pcrit>\d+)?\s+(?P<slide_perfect>\d+)?\s+(?P<slide_great>\d+)?\s+(?P<slide_good>\d+)?\s+(?P<slide_miss>\d+)?\n"
    r"TOUCH:\s+(?P<touch_pcrit>\d+)?\s+(?P<touch_perfect>\d+)?\s+(?P<touch_great>\d+)?\s+(?P<touch_good>\d+)?\s+(?P<touch_miss>\d+)?\n"
    r"BREAK:\s+(?P<break_pcrit>\d+)?\s+(?P<break_perfect>\d+)?\s+(?P<break_great>\d+)?\s+(?P<break_good>\d+)?\s+(?P<break_miss>\d+)?"
)
RE_ACHIEVEMENT = re.compile(r"Accuracy: \*\*([\d\.]+)%\*\*")


@dataclass
class BreakDistribution:
    break_2550: int
    break_2500: int
    break_2000: int
    break_1500: int
    break_1250: int


@dataclass
class JudgementBreakdownResult:
    base_score_per_note: Decimal
    bonus_score_per_break: Decimal
    distributions: list[BreakDistribution]


def calculate_breakdown(judgements: list[list[int]], achievement: Decimal):
    (
        tap_judgements,
        hold_judgements,
        slide_judgements,
        touch_judgements,
        break_judgements,
    ) = judgements
    tap_touch_count = sum(tap_judgements) + sum(touch_judgements)
    hold_count = sum(hold_judgements)
    slide_count = sum(slide_judgements)
    break_count = sum(break_judgements)

    base_score_per_note = MAX_BASE_SCORE / (
        tap_touch_count
        + hold_count * HOLD_PER_TAP
        + slide_count * SLIDE_PER_TAP
        + break_count * BREAK_PER_TAP
    )
    bonus_score_per_break = MAX_BREAK_BONUS / break_count

    # fmt: off
    known_base_score = (
        base_score_per_note * (tap_judgements[0] + tap_judgements[1] + touch_judgements[0] + touch_judgements[1])
        + base_score_per_note * GREAT_PER_TAP * (tap_judgements[2] + touch_judgements[2])
        + base_score_per_note * GOOD_PER_TAP * (tap_judgements[3] + touch_judgements[3])
        + base_score_per_note * HOLD_PER_TAP * (hold_judgements[0] + hold_judgements[1])
        + base_score_per_note * HOLD_PER_TAP * GREAT_PER_TAP * hold_judgements[2]
        + base_score_per_note * HOLD_PER_TAP * GOOD_PER_TAP * hold_judgements[3]
        + base_score_per_note * SLIDE_PER_TAP * (slide_judgements[0] + slide_judgements[1])
        + base_score_per_note * SLIDE_PER_TAP * GREAT_PER_TAP * slide_judgements[2]
        + base_score_per_note * SLIDE_PER_TAP * GOOD_PER_TAP * slide_judgements[3]
        + base_score_per_note * BREAK_PER_TAP * (break_judgements[0] + break_judgements[1])
        + base_score_per_note * GOOD_BREAK_PER_TAP * break_judgements[3]
    )
    known_bonus_score = (
        bonus_score_per_break * break_judgements[0]
        + bonus_score_per_break * GREAT_BREAK_BONUS * break_judgements[2]
        + bonus_score_per_break * GOOD_BREAK_BONUS * break_judgements[3]
    )
    # fmt: on

    unknown_score = achievement - known_base_score - known_bonus_score

    solver = Solver()

    break_2550 = Int("break_2550")
    break_2500 = Int("break_2500")
    break_2000 = Int("break_2000")
    break_1500 = Int("break_1500")
    break_1250 = Int("break_1250")

    solver.add(
        break_2550 >= 0,
        break_2500 >= 0,
        break_2000 >= 0,
        break_1500 >= 0,
        break_1250 >= 0,
        break_2550 + break_2500 == break_judgements[1],
        break_2000 + break_1500 + break_1250 == break_judgements[2],
        ToInt(
            (
                bonus_score_per_break * RealVal("0.75") * break_2550
                + bonus_score_per_break * RealVal("0.5") * break_2500
                + base_score_per_note * RealVal("4") * break_2000
                + base_score_per_note * RealVal("3") * break_1500
                + base_score_per_note * RealVal("2.5") * break_1250
            )
            * RealVal("1000")
        )
        == ToInt(unknown_score * RealVal("1000")),
    )

    distributions: list[BreakDistribution] = []

    while solver.check() not in (unsat, unknown):
        model = solver.model()
        distribution = BreakDistribution(
            model[break_2550],
            model[break_2500],
            model[break_2000],
            model[break_1500],
            model[break_1250],
        )
        distributions.append(distribution)

        solver.add(
            Or(
                break_2550 != model[break_2550],
                break_2500 != model[break_2500],
                break_2000 != model[break_2000],
                break_1500 != model[break_1500],
                break_1250 != model[break_1250],
            )
        )

    return JudgementBreakdownResult(
        base_score_per_note, bonus_score_per_break, distributions
    )


def floor_to_ndp(number: Decimal, dp: int) -> Decimal:
    if not isinstance(number, Decimal):
        msg = "Flooring an arbitrary floating point number will cause inaccuracies. Use the Decimal class."
        raise TypeError(msg)

    with decimal.localcontext() as ctx:
        ctx.rounding = decimal.ROUND_FLOOR
        return round(Decimal(number), dp)


class MaimaiCog(commands.Cog, name="Maimai"):
    def __init__(self, bot: "MinimBot") -> None:
        self.bot: "MinimBot" = bot
        self.allowlister: "AllowlisterCog" = self.bot.get_cog("Allowlister")  # pyright: ignore[reportAttributeAccessIssue]

    @override
    def cog_check(self, ctx: Context) -> bool:
        return (
            self.allowlister.is_allowlisted_context(ctx)
            and ctx.channel.id in self.allowlister.thread_ids
        )

    @commands.command("breakdown")
    async def breakdown(self, ctx: Context):
        """Calculate the break distribution for a maimai score from mimi xd bot."""

        if (reference := ctx.message.reference) is None or reference.message_id is None:
            await ctx.reply(
                content="Please reply to a mimi xd bot score details embed.",
                mention_author=False,
            )
            return

        message = await ctx.channel.fetch_message(reference.message_id)

        if (
            message.author.id != 604641359416131585
            or len(message.embeds) != 1
            or (embed := message.embeds[0]).description is None
            or "Details:" not in embed.description
        ):
            await ctx.reply(
                content="Please reply to a mimi xd bot score details embed.",
                mention_author=False,
            )
            return

        achievement_match = RE_ACHIEVEMENT.search(embed.description)
        judgement_details_match = RE_JUDGEMENT_DETAILS.search(embed.description)

        if achievement_match is None or judgement_details_match is None:
            await ctx.reply(
                content="Please reply to a mimi xd bot score details embed.",
                mention_author=False,
            )
            return

        achievement = Decimal(achievement_match.group(1))
        judgements: list[list[int]] = []

        for note_type in ("tap", "hold", "slide", "touch", "break"):
            note_judgements: list[int] = [
                int(judgement_details_match.group(f"{note_type}_{judgement_type}") or 0)
                for judgement_type in ("pcrit", "perfect", "great", "good", "miss")
            ]

            judgements.append(note_judgements)

        start_time = time.perf_counter_ns()
        result = calculate_breakdown(judgements, achievement)
        end_time = time.perf_counter_ns()

        if len(result.distributions) == 0:
            await ctx.reply(
                content="No valid break distributions found.", mention_author=False
            )
            return

        distribution = result.distributions[0]
        tap_great_loss = -floor_to_ndp(
            result.base_score_per_note * (1 - GREAT_PER_TAP) * judgements[0][2], 4
        )
        tap_good_loss = -floor_to_ndp(
            result.base_score_per_note * (1 - GOOD_PER_TAP) * judgements[0][3], 4
        )
        tap_miss_loss = -floor_to_ndp(result.base_score_per_note * judgements[0][4], 4)
        hold_great_loss = -floor_to_ndp(
            result.base_score_per_note
            * HOLD_PER_TAP
            * (1 - GREAT_PER_TAP)
            * judgements[1][2],
            4,
        )
        hold_good_loss = -floor_to_ndp(
            result.base_score_per_note
            * HOLD_PER_TAP
            * (1 - GOOD_PER_TAP)
            * judgements[1][3],
            4,
        )
        hold_miss_loss = -floor_to_ndp(
            result.base_score_per_note * HOLD_PER_TAP * judgements[1][4],
            4,
        )
        slide_great_loss = -floor_to_ndp(
            result.base_score_per_note
            * SLIDE_PER_TAP
            * (1 - GREAT_PER_TAP)
            * judgements[2][2],
            4,
        )
        slide_good_loss = -floor_to_ndp(
            result.base_score_per_note
            * SLIDE_PER_TAP
            * (1 - GOOD_PER_TAP)
            * judgements[2][3],
            4,
        )
        slide_miss_loss = -floor_to_ndp(
            result.base_score_per_note * SLIDE_PER_TAP * judgements[2][4],
            4,
        )
        touch_great_loss = -floor_to_ndp(
            result.base_score_per_note * (1 - GREAT_PER_TAP) * judgements[3][2], 4
        )
        touch_good_loss = -floor_to_ndp(
            result.base_score_per_note * (1 - GOOD_PER_TAP) * judgements[3][3], 4
        )
        touch_miss_loss = -floor_to_ndp(
            result.base_score_per_note * judgements[3][4], 4
        )
        break_perfect_loss = -floor_to_ndp(
            distribution.break_2550
            * (1 - BREAK_2550_BONUS)
            * result.bonus_score_per_break
            + distribution.break_2500
            * (1 - BREAK_2500_BONUS)
            * result.bonus_score_per_break,
            4,
        )
        break_great_loss = -floor_to_ndp(
            result.base_score_per_note
            * BREAK_PER_TAP
            * (1 - GREAT_PER_TAP)
            * distribution.break_2000
            + result.base_score_per_note
            * BREAK_PER_TAP
            * Decimal("0.4")
            * distribution.break_1500
            + result.base_score_per_note
            * BREAK_PER_TAP
            * Decimal("0.5")
            * distribution.break_1250
            + result.bonus_score_per_break * Decimal("0.6") * judgements[4][2],
            4,
        )
        break_good_loss = -floor_to_ndp(
            result.base_score_per_note
            * BREAK_PER_TAP
            * Decimal("0.6")
            * judgements[4][3]
            + result.bonus_score_per_break * Decimal("0.7") * judgements[4][3],
            4,
        )
        break_miss_loss = -floor_to_ndp(
            result.base_score_per_note * BREAK_PER_TAP * judgements[4][4]
            + result.bonus_score_per_break * judgements[4][4],
            4,
        )
        content = (
            f"Found {len(result.distributions)} break distributions in {(end_time - start_time) // 1_000_000 / 1000} second(s). Only showing first result.\n"
            "```\n"
            f"Type▸   Perfect▸    Great▸     Good▸     Miss\n"
            f"TAP:   -0.0000%  {tap_great_loss}%  {tap_good_loss}%  {tap_miss_loss}%\n"
            f"HOLD:  -0.0000%  {hold_great_loss}%  {hold_good_loss}%  {hold_miss_loss}%\n"
            f"SLIDE: -0.0000%  {slide_great_loss}%  {slide_good_loss}%  {slide_miss_loss}%\n"
            f"TOUCH: -0.0000%  {touch_great_loss}%  {touch_good_loss}%  {touch_miss_loss}%\n"
            f"BREAK: {break_perfect_loss}%  {break_great_loss}%  {break_good_loss}%  {break_miss_loss}%\n"
            "\n"
            f"Perfect breaks: [{distribution.break_2550}, {distribution.break_2500}]\n"
            f"Great breaks: [{distribution.break_2000}, {distribution.break_1500}, {distribution.break_1250}]\n"
            "```"
        )
        await ctx.reply(content=content, mention_author=False)


async def setup(bot: "MinimBot"):
    await bot.add_cog(MaimaiCog(bot))
