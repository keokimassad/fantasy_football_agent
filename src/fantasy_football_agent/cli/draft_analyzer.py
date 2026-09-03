"""Command-line entry point for inspecting the current draft state."""

import argparse
from pathlib import Path

from fantasy_football_agent.application_paths import ApplicationPaths
from fantasy_football_agent.draft.analysis import get_position_exposure
from fantasy_football_agent.draft.decision_packet import build_draft_decision_packet
from fantasy_football_agent.draft.models import DraftState
from fantasy_football_agent.draft.rankings import (
    get_available_players,
    get_position_tier_summary,
    get_scarcity_flags,
    get_tier_coverage,
    load_rankings,
    next_position_tier,
    remaining_in_player_tier,
)
from fantasy_football_agent.draft.recommendations import (
    CandidateRecommendation,
    build_candidate_recommendations,
    evaluate_candidates,
)
from fantasy_football_agent.draft.state import (
    get_active_lookahead_window,
    get_all_team_open_starter_slots,
    get_all_team_position_counts,
    get_team_context_for_picks,
    get_team_roster,
    get_total_draft_picks,
    is_draft_complete,
    load_draft_state,
    load_league_config,
    team_for_overall_pick,
    validate_draft_state,
)
from fantasy_football_agent.draft.sync_status import (
    DraftStateStaleError,
    require_fresh_draft_state,
)
from fantasy_football_agent.observability import (
    record_decision_blocked,
    record_decision_packet,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze the current fantasy football draft state."
    )

    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Directory containing the config and data directories.",
    )

    return parser.parse_args()


def _print_candidate_recommendations(
    recommendations: list[CandidateRecommendation],
) -> None:
    """Print a compact shortlist appropriate to the current draft phase."""
    print()

    if recommendations and not recommendations[0].evaluation.is_on_clock:
        decision_pick = recommendations[0].evaluation.decision_pick
        print(f"Decision prep shortlist for pick #{decision_pick}:")
    else:
        print("Deterministic shortlist:")

    if not recommendations:
        print("  No available candidates.")
        return

    for index, recommendation in enumerate(recommendations, start=1):
        evaluation = recommendation.evaluation
        player = evaluation.player

        tier_display = f"T{player.manual_tier}" if player.manual_tier is not None else "T-"
        adp_display = f"{player.adp:.1f}" if player.adp is not None else "-"
        tier_remaining_display = (
            str(evaluation.tier_remaining) if evaluation.tier_remaining is not None else "-"
        )
        next_tier_display = f"T{evaluation.next_tier}" if evaluation.next_tier is not None else "-"
        signals_display = ", ".join(recommendation.signals) if recommendation.signals else "-"

        if evaluation.is_on_clock:
            print(
                f"  {index}. {player.name} "
                f"| {player.position} {tier_display} "
                f"| Desirability {recommendation.desirability.value} "
                f"| Urgency {recommendation.priority.value}"
            )
            print(
                f"     Rank #{player.rank} | ADP {adp_display} "
                f"| Fit {evaluation.roster_fit.value} "
                f"| Roster utility {recommendation.roster_utility.value} "
                f"| Loss cost {recommendation.loss_cost.value} "
                f"| Return risk {recommendation.return_risk.value}"
            )
        else:
            print(
                f"  {index}. {player.name} "
                f"| {player.position} {tier_display} "
                f"| Desirability {recommendation.desirability.value} "
                f"| Availability risk {recommendation.availability_risk.value}"
            )
            print(
                f"     Rank #{player.rank} | ADP {adp_display} "
                f"| Fit {evaluation.roster_fit.value} "
                f"| Roster utility {recommendation.roster_utility.value}"
            )

        print(
            f"     Tier left {tier_remaining_display} "
            f"| Next {next_tier_display} "
            f"| Why: {signals_display}"
        )


def _print_stale_state_error(error: DraftStateStaleError) -> None:
    """Print a dominant failure banner when local draft state is known stale."""
    failure = error.failure
    print()
    print("=" * 72)
    print("DRAFT STATE STALE — RECOMMENDATIONS DISABLED")
    print("=" * 72)
    print(f"Reason: {failure.message}")
    print(f"Local state is waiting at pick #{failure.local_current_overall_pick}.")
    print(f"Yahoo evidence reached at least pick #{failure.observed_yahoo_pick}.")
    print("Copy a Yahoo range containing the unresolved picks and rerun ffmock.")
    print("=" * 72)


def _print_status_footer(
    *,
    state: DraftState,
    drafting_team: int,
    target_pick: int | None,
    active_picks: list[tuple[int, int]],
    recommendations: list[CandidateRecommendation],
) -> None:
    """Repeat live status and the leading shortlist at the bottom of the report."""
    is_on_clock = drafting_team == state.my_draft_slot

    print()
    print("-" * 72)

    if is_on_clock:
        print(f"STATUS: ON CLOCK — PICK #{state.current_overall_pick}")
        if target_pick is None:
            print("NEXT USER PICK: none — final user selection")
        else:
            print(
                f"NEXT USER PICK: #{target_pick} | "
                f"{len(active_picks)} opponent selections before return"
            )
        shortlist_label = "TOP SHORTLIST"
    else:
        print(f"STATUS: WAITING — CURRENT #{state.current_overall_pick} (T{drafting_team})")
        if target_pick is None:
            print("NEXT USER PICK: none — user selections complete")
        else:
            print(f"NEXT USER PICK: #{target_pick} | {len(active_picks)} selections away")
        shortlist_label = "TOP PREP"

    print(f"{shortlist_label}:")
    if not recommendations:
        print("  No available candidates")
    else:
        for index, recommendation in enumerate(recommendations[:3], start=1):
            player = recommendation.evaluation.player
            print(
                f"  {index}. {player.name} — {player.position}, {player.team} "
                f"| Yahoo Rank #{player.rank}"
            )

    print("-" * 72)


def main() -> None:
    """Load the active workspace and print a deterministic draft analysis."""
    args = _parse_args()

    paths = ApplicationPaths(workspace=args.workspace.resolve())

    league = load_league_config(paths.league_config)
    state = load_draft_state(paths.draft_state)

    validate_draft_state(state, league)

    try:
        require_fresh_draft_state(paths.draft_sync_status, state)
    except DraftStateStaleError as error:
        record_decision_blocked(
            paths,
            state,
            source="cli",
            reason=error.failure.message,
        )
        _print_stale_state_error(error)
        raise SystemExit(1) from error

    print()
    print("=== Fantasy Draft Assistant ===")
    print(f"League: {league.league_name}")
    print(f"Teams: {league.teams}")
    print(f"Draft: {state.draft_id} ({state.session_type})")
    print(f"My draft slot: {state.my_draft_slot}")
    print(f"Current overall pick: {state.current_overall_pick}")

    if is_draft_complete(state, league):
        packet = build_draft_decision_packet([], state, league)
        record_decision_packet(paths, state, packet, source="cli")
        print(f"Draft complete after #{get_total_draft_picks(league)}.")

        my_roster = get_team_roster(
            state,
            state.my_draft_slot,
        )

        print()
        print("My roster:")

        if not my_roster:
            print("  No players drafted.")
        else:
            for pick in my_roster:
                print(f"  {pick.position}: {pick.player} (Pick {pick.overall})")

        print()
        print("-" * 72)
        total_picks = get_total_draft_picks(league)
        print(f"STATUS: COMPLETE — {total_picks}/{total_picks} picks")
        print("-" * 72)
        return

    rankings = load_rankings(paths.rankings, paths.player_overrides)

    available = get_available_players(
        rankings,
        state,
    )

    candidate_evaluations = evaluate_candidates(
        available,
        state,
        league,
    )
    packet = build_draft_decision_packet(
        candidate_evaluations,
        state,
        league,
    )
    record_decision_packet(paths, state, packet, source="cli")

    recommendations = build_candidate_recommendations(
        candidate_evaluations,
        limit=5,
    )

    drafting_team = team_for_overall_pick(
        state.current_overall_pick,
        league.teams,
    )

    print(f"Team currently drafting: {drafting_team}")

    _print_candidate_recommendations(recommendations)

    my_roster = get_team_roster(
        state,
        state.my_draft_slot,
    )

    print()
    print("My roster:")

    if not my_roster:
        print("  No players drafted yet.")
    else:
        for pick in my_roster:
            print(f"  {pick.position}: {pick.player} (Pick {pick.overall})")

    print()
    print("Top available players:")

    for player in available[:15]:
        adp_display = f"{player.adp:.1f}" if player.adp is not None else "-"

        drafted_display = (
            f"{player.drafted_percentage:.0f}%" if player.drafted_percentage is not None else "-"
        )

        tier_display = str(player.manual_tier) if player.manual_tier is not None else "-"

        tier_remaining = remaining_in_player_tier(
            available,
            player,
        )

        tier_remaining_display = str(tier_remaining) if tier_remaining is not None else "-"

        next_tier = next_position_tier(
            available,
            player,
        )

        next_tier_display = str(next_tier) if next_tier is not None else "-"

        scarcity_flags = get_scarcity_flags(
            available,
            player,
        )

        scarcity_display = ",".join(scarcity_flags) if scarcity_flags else "-"

        print(
            f"  #{player.rank:<3} "
            f"{player.name:<24} "
            f"{player.position:<4} "
            f"{player.team:<3} "
            f"ADP {adp_display:<6} "
            f"Drafted {drafted_display:<5} "
            f"Bye {player.bye:<2} "
            f"Tier {tier_display:<2} "
            f"Remaining {tier_remaining_display:<2} "
            f"Next {next_tier_display:<2} "
            f"Flags {scarcity_display}"
        )

    tier_summary = get_position_tier_summary(available)

    print()
    print("Tier scarcity summary:")

    if not tier_summary:
        print("  No manual tiers assigned yet.")
    else:
        for position in sorted(tier_summary):
            tiers = tier_summary[position]

            tier_text = ", ".join(f"T{tier}: {count}" for tier, count in sorted(tiers.items()))

            print(f"  {position}: {tier_text}")

    print()
    print("Tier coverage:")

    for position in ["QB", "RB", "WR", "TE"]:
        tiered, total = get_tier_coverage(
            rankings,
            position,
        )

        print(f"  {position}: {tiered}/{total} players tiered")

    team_rosters = get_all_team_position_counts(
        state,
        league,
    )

    print()
    print("Team roster construction:")

    positions_to_show = [
        "QB",
        "RB",
        "WR",
        "TE",
        "K",
        "DEF",
    ]

    for team_id in range(1, league.teams + 1):
        counts = team_rosters[team_id]

        roster_display = "  ".join(
            f"{position} {counts.get(position, 0)}" for position in positions_to_show
        )

        my_team_marker = " <-- MY TEAM" if team_id == state.my_draft_slot else ""

        print(f"  Team {team_id:<2}: {roster_display}{my_team_marker}")

    open_starter_slots = get_all_team_open_starter_slots(
        state,
        league,
    )

    print()
    print("Open starter slots:")

    positions_to_show = [
        "QB",
        "RB",
        "WR",
        "TE",
        "FLEX",
        "K",
        "DEF",
    ]

    for team_id in range(1, league.teams + 1):
        slots = open_starter_slots[team_id]

        slot_display = "  ".join(
            f"{position} {slots.get(position, 0)}" for position in positions_to_show
        )

        my_team_marker = " <-- MY TEAM" if team_id == state.my_draft_slot else ""

        print(f"  Team {team_id:<2}: {slot_display}{my_team_marker}")

    _, target_pick, active_picks = get_active_lookahead_window(
        state=state,
        league=league,
    )

    is_on_clock = drafting_team == state.my_draft_slot

    print()
    print("Active lookahead:")

    if is_on_clock:
        print(f"  I am currently on the clock at #{state.current_overall_pick}.")

        if target_pick is None:
            print("  This is my final draft selection.")
            print(f"  Opponent selections remaining afterward: {len(active_picks)}")
        else:
            print(f"  My following pick: #{target_pick}")
            print(f"  Opponent selections if I wait: {len(active_picks)}")

    else:
        print(f"  Current pick: #{state.current_overall_pick}")

        if target_pick is None:
            print("  My draft selections are complete.")
            print(f"  Selections remaining in the league draft: {len(active_picks)}")
        else:
            print(f"  My next pick: #{target_pick}")
            print(f"  Selections before my pick: {len(active_picks)}")

    if active_picks:
        pick_sequence = " -> ".join(
            f"#{overall_pick} T{team_id}" for overall_pick, team_id in active_picks
        )

        print(f"  Pick sequence: {pick_sequence}")

    lookahead_context = get_team_context_for_picks(
        state=state,
        league=league,
        picks=active_picks,
    )

    print()
    print("Opponent lookahead:")

    if not lookahead_context:
        print("  No opponent selections in the active lookahead window.")

    else:
        for team_id, context in lookahead_context.items():
            slots = context.open_starter_slots

            picks_display = ", ".join(f"#{pick}" for pick in context.overall_picks)

            needs_display = "  ".join(
                f"{position} {slots.get(position, 0)}"
                for position in [
                    "QB",
                    "RB",
                    "WR",
                    "TE",
                    "FLEX",
                ]
            )

            print(
                f"  Team {team_id:<2} "
                f"| Picks: {picks_display:<9} "
                f"| Chances: "
                f"{context.pick_count} "
                f"| {needs_display}"
            )

    position_exposure = get_position_exposure(
        league=league,
        lookahead_context=lookahead_context,
    )

    print()

    if is_on_clock:
        print("Position exposure if I wait until my following pick:")
    else:
        print("Position exposure before my next pick:")

    for position in [
        "QB",
        "RB",
        "WR",
        "TE",
        "K",
        "DEF",
    ]:
        exposure = position_exposure[position]

        direct_teams = exposure.direct_need_teams

        flex_teams = exposure.flex_only_teams

        direct_display = ", ".join(f"T{team}" for team in direct_teams) if direct_teams else "-"

        flex_display = ", ".join(f"T{team}" for team in flex_teams) if flex_teams else "-"

        print(
            f"  {position:<3} "
            f"| Direct: {direct_display:<20} "
            f"| Flex-only: {flex_display:<20} "
            f"| Selection chances: "
            f"{exposure.selection_chances}"
        )

    _print_status_footer(
        state=state,
        drafting_team=drafting_team,
        target_pick=target_pick,
        active_picks=active_picks,
        recommendations=recommendations,
    )


if __name__ == "__main__":
    main()
