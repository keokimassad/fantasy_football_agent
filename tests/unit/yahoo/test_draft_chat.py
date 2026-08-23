"""Unit tests for Yahoo draft-chat parsing and player resolution."""

from collections.abc import Callable

import pytest

from fantasy_football_agent.draft.models import Player
from fantasy_football_agent.yahoo.draft_chat import (
    AmbiguousYahooPlayerError,
    YahooDraftChatPick,
    parse_yahoo_draft_chat,
    resolve_yahoo_chat_player,
)

pytestmark = pytest.mark.unit


def test_parse_yahoo_chat_handles_status_and_chat_noise() -> None:
    """
    GIVEN: Yahoo draft chat containing selections, status, and arbitrary chat events
    WHEN: the copied text is parsed
    THEN: only structurally valid draft selections are returned
    """
    text = """
    26
    Wyatt
    J. Love
    Q
    RB
    Ari
    Bye 14

    27
    chris
    G. Pickens
    WR
    Dal
    Bye 14

    chrischris left
    good pick
    I wanted him too
    chrischris joined

    28
    Wes
    C. Olave
    WR
    NO
    Bye 8

    29
    Jace
    T. McBride
    TE
    Ari
    Bye 14

    30
    You
    M. Nabers
    Q
    WR
    NYG
    Bye 8

    31
    You
    B. Hall
    Q
    RB
    NYJ
    Bye 13
    """

    picks = parse_yahoo_draft_chat(text)

    assert [pick.overall for pick in picks] == [26, 27, 28, 29, 30, 31]

    assert picks[0] == YahooDraftChatPick(
        overall=26,
        drafter="Wyatt",
        player_reference="J. Love",
        position="RB",
        team="ARI",
        bye=14,
        status="Q",
    )

    assert picks[1].status is None
    assert picks[4].drafter == "You"
    assert picks[4].player_reference == "M. Nabers"


def test_parse_yahoo_chat_accepts_markdown_copy_format() -> None:
    """
    GIVEN: Yahoo selection text represented with Markdown bolding and list markers
    WHEN: the copied text is parsed
    THEN: formatting markers do not affect the parsed selection
    """
    text = """
    **30**
    **You**
    **M. Nabers**
    **Q**
    - **WR**
    - **NYG**
    - **Bye 8**
    """

    picks = parse_yahoo_draft_chat(text)

    assert picks == [
        YahooDraftChatPick(
            overall=30,
            drafter="You",
            player_reference="M. Nabers",
            position="WR",
            team="NYG",
            bye=8,
            status="Q",
        )
    ]


def test_parse_yahoo_chat_accepts_missing_bye_value() -> None:
    """
    GIVEN: a Yahoo selection whose bye value has not rendered
    WHEN: the copied text is parsed
    THEN: the selection is retained with no bye value
    """
    text = """
    10
    You
    C. Lamb
    WR
    Dal
    -
    """

    picks = parse_yahoo_draft_chat(text)

    assert picks == [
        YahooDraftChatPick(
            overall=10,
            drafter="You",
            player_reference="C. Lamb",
            position="WR",
            team="DAL",
            bye=None,
        )
    ]


def test_parse_yahoo_chat_ignores_incomplete_final_pick() -> None:
    """
    GIVEN: Yahoo text ending while the newest selection is still rendering
    WHEN: the copied text is parsed
    THEN: the incomplete trailing selection is ignored
    """
    text = """
    8
    Wes
    J. Smith-Njigba
    WR
    Sea
    Bye 11

    9
    Jace
    J. Cook III
    """

    picks = parse_yahoo_draft_chat(text)

    assert [pick.overall for pick in picks] == [8]


def test_parse_yahoo_chat_ignores_numeric_chat_message() -> None:
    """
    GIVEN: arbitrary chat containing a numeric line that is not a draft selection
    WHEN: the copied text is parsed
    THEN: the numeric message is not mistaken for a pick
    """
    text = """
    2026
    this is not a pick
    RB
    all day

    28
    Wes
    C. Olave
    WR
    NO
    Bye 8
    """

    picks = parse_yahoo_draft_chat(text)

    assert [pick.overall for pick in picks] == [28]


def test_resolve_yahoo_chat_player_matches_abbreviated_name(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: rankings containing Malik Nabers
    WHEN: Yahoo reports M. Nabers with matching position and NFL team
    THEN: the full ranked player identity is resolved
    """
    nabers = make_player(
        name="Malik Nabers",
        position="WR",
        team="NYG",
        yahoo_player_id=10024,
    )

    chat_pick = YahooDraftChatPick(
        overall=30,
        drafter="You",
        player_reference="M. Nabers",
        position="WR",
        team="NYG",
        bye=8,
        status="Q",
    )

    resolved = resolve_yahoo_chat_player(
        [nabers],
        chat_pick,
    )

    assert resolved is nabers


def test_resolve_yahoo_chat_player_uses_position_and_team(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: two players sharing the Yahoo abbreviation J. Love
    WHEN: Yahoo also supplies the selected player's position and NFL team
    THEN: the metadata identifies the intended ranked player
    """
    jordan_love = make_player(
        name="Jordan Love",
        position="QB",
        team="GB",
        yahoo_player_id=20001,
    )
    jeremiyah_love = make_player(
        name="Jeremiyah Love",
        position="RB",
        team="ARI",
        yahoo_player_id=20002,
    )

    chat_pick = YahooDraftChatPick(
        overall=26,
        drafter="Wyatt",
        player_reference="J. Love",
        position="RB",
        team="ARI",
        bye=14,
        status="Q",
    )

    resolved = resolve_yahoo_chat_player(
        [jordan_love, jeremiyah_love],
        chat_pick,
    )

    assert resolved is jeremiyah_love


def test_resolve_yahoo_chat_player_reports_true_ambiguity(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: Bijan Robinson and Brian Robinson share Yahoo abbreviation and metadata
    WHEN: neither player can be eliminated from consideration
    THEN: resolution exposes both candidates instead of guessing
    """
    bijan = make_player(
        rank=2,
        adp=1.9,
        name="Bijan Robinson",
        position="RB",
        team="ATL",
        bye=11,
        yahoo_player_id=40055,
    )
    brian = make_player(
        rank=155,
        adp=123.1,
        name="Brian Robinson",
        position="RB",
        team="ATL",
        bye=11,
        yahoo_player_id=34054,
    )

    chat_pick = YahooDraftChatPick(
        overall=2,
        drafter="Chris",
        player_reference="B. Robinson",
        position="RB",
        team="ATL",
        bye=11,
    )

    with pytest.raises(AmbiguousYahooPlayerError) as error:
        resolve_yahoo_chat_player(
            [bijan, brian],
            chat_pick,
        )

    assert error.value.candidates == (bijan, brian)


def test_resolve_yahoo_chat_player_can_exclude_already_drafted_candidate(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: two matching B. Robinson players but Bijan was previously drafted
    WHEN: a genuinely new Yahoo pick is resolved with Bijan excluded
    THEN: Brian Robinson is resolved without user interaction
    """
    bijan = make_player(
        name="Bijan Robinson",
        position="RB",
        team="ATL",
        bye=11,
        yahoo_player_id=40055,
    )
    brian = make_player(
        name="Brian Robinson",
        position="RB",
        team="ATL",
        bye=11,
        yahoo_player_id=34054,
    )

    chat_pick = YahooDraftChatPick(
        overall=126,
        drafter="Chris",
        player_reference="B. Robinson",
        position="RB",
        team="ATL",
        bye=11,
    )

    resolved = resolve_yahoo_chat_player(
        [bijan, brian],
        chat_pick,
        excluded_yahoo_player_ids={bijan.yahoo_player_id},
    )

    assert resolved is brian


def test_resolve_yahoo_chat_player_rejects_unknown_player(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: rankings without a player matching Yahoo's abbreviation and metadata
    WHEN: the Yahoo selection is resolved
    THEN: resolution fails instead of guessing a player identity
    """
    rankings = [
        make_player(
            name="Malik Nabers",
            position="WR",
            team="NYG",
            yahoo_player_id=10024,
        )
    ]

    chat_pick = YahooDraftChatPick(
        overall=10,
        drafter="You",
        player_reference="C. Lamb",
        position="WR",
        team="DAL",
        bye=None,
    )

    with pytest.raises(
        ValueError,
        match="Could not resolve Yahoo draft-chat player",
    ):
        resolve_yahoo_chat_player(
            rankings,
            chat_pick,
        )


def test_parse_yahoo_chat_ignores_block_without_valid_pick_structure() -> None:
    """
    GIVEN: numeric chat content without a valid Yahoo draft-selection structure
    WHEN: the copied text is parsed
    THEN: the malformed candidate block is ignored
    """
    text = """
    42
    Chris
    nice pick
    definitely taking a RB next
    """

    picks = parse_yahoo_draft_chat(text)

    assert picks == []


def test_resolve_yahoo_chat_player_accepts_exact_full_name(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: Yahoo reports a player's complete name
    WHEN: the name and metadata match one ranked player
    THEN: the exact ranked player is resolved
    """
    nabers = make_player(
        name="Malik Nabers",
        position="WR",
        team="NYG",
        bye=8,
        yahoo_player_id=10024,
    )

    chat_pick = YahooDraftChatPick(
        overall=30,
        drafter="You",
        player_reference="Malik Nabers",
        position="WR",
        team="NYG",
        bye=8,
    )

    resolved = resolve_yahoo_chat_player([nabers], chat_pick)

    assert resolved is nabers


def test_resolve_yahoo_chat_player_does_not_require_bye_match(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: Yahoo reports stale or mismatched bye metadata for an otherwise unique player
    WHEN: the player reference is resolved
    THEN: the mismatched bye does not prevent deterministic name and team resolution
    """
    nabers = make_player(
        name="Malik Nabers",
        position="WR",
        team="NYG",
        bye=8,
        yahoo_player_id=10024,
    )

    chat_pick = YahooDraftChatPick(
        overall=30,
        drafter="You",
        player_reference="M. Nabers",
        position="WR",
        team="NYG",
        bye=9,
    )

    resolved = resolve_yahoo_chat_player([nabers], chat_pick)

    assert resolved is nabers


def test_resolve_yahoo_chat_player_rejects_when_all_matches_are_excluded(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: a Yahoo player reference whose only matching player was already drafted
    WHEN: that player's Yahoo ID is excluded from a new-pick resolution
    THEN: resolution rejects the duplicate selection
    """
    nabers = make_player(
        name="Malik Nabers",
        position="WR",
        team="NYG",
        bye=8,
        yahoo_player_id=10024,
    )

    chat_pick = YahooDraftChatPick(
        overall=31,
        drafter="Chris",
        player_reference="M. Nabers",
        position="WR",
        team="NYG",
        bye=8,
    )

    with pytest.raises(
        ValueError,
        match="have already been drafted",
    ):
        resolve_yahoo_chat_player(
            [nabers],
            chat_pick,
            excluded_yahoo_player_ids={nabers.yahoo_player_id},
        )
