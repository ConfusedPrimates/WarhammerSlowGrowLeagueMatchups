import gspread
from oauth2client.service_account import ServiceAccountCredentials
import random
from itertools import combinations
import re
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition
from functools import lru_cache

# -----------------------------
# AUTH
# -----------------------------
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    r"insert-file-location", scope
)

client = gspread.authorize(creds)

# -----------------------------
# OPEN SHEETS
# -----------------------------
players_sheet = client.open("League sign up (Responses)").sheet1
history_sheet = client.open("League Match Ups")
victories_sheet = client.open("victory tracker").sheet1

# -----------------------------
# LOAD PLAYERS
# -----------------------------
players_data = players_sheet.get_all_records()
players = []
player_to_discord = {}

for p in players_data:
    name = p["Full Name"]
    discord = p["Discord username"]
    
    players.append(name)
    player_to_discord[name] = discord
# -----------------------------
# FIND WEEK SHEETS
# -----------------------------
history_data = history_sheet.worksheets()

week_sheets = []
week_numbers = []

for sheet in history_data:
    match = re.match(r"Week (\d+)", sheet.title)
    if match:
        week_num = int(match.group(1))
        week_sheets.append((week_num, sheet))
        week_numbers.append(week_num)

#sort by week
week_sheets.sort(key=lambda x: x[0])

# -----------------------------
# LOAD PLAYER WINS
# -----------------------------
victory_records = victories_sheet.get_all_records()

player_wins = {
    player: 0
    for player in players
}

# Discord username -> Full Name
discord_to_player = {
    discord.strip().lower(): player
    for player, discord in player_to_discord.items()
}


for row in victory_records:
    name = row["Name"].strip().lower()
    victory_type = row["Victory type"].strip()

  # Make sure the Discord username belongs to a rostered player
    if discord not in discord_to_player:
        print(
            f"WARNING: Discord username '{discord}' "
            f"was submitted but is not in the roster."
        )
        continue

    if victory_type == "Major victory":
        if name in player_wins:
            player_wins[name] += 3
    elif victory_type == "Minor victory":
        if name in player_wins:
            player_wins[name] += 2
    elif victory_type == "Draw":
        if name in player_wins:
            player_wins[name] += 1
    else:
        print(
            f"WARNING: Unknown victory type "
            f"'{victory_type}' submitted by '{discord}'."
        )


# -----------------------------
# LOAD MATCH HISTORY
# -----------------------------
past_matchups = set()

for week_num, sheet in week_sheets:
    records = sheet.get_all_records()
    for row in records:
        pair = tuple(sorted([row["Player1"], row["Player2"]]))
        past_matchups.add(pair)

# -----------------------------
# DETERMINE NEXT WEEK
# -----------------------------
next_week = max(week_numbers) + 1 if week_numbers else 1

print(
    f"Generating Week {next_week}..."
)

# -----------------------------
# GENERATE MATCHUPS
# -----------------------------
all_matchups = set(tuple(sorted(pair)) for pair in combinations(players, 2))
remaining_matchups = list(all_matchups - past_matchups)

# Reset if needed
if not remaining_matchups:
    print("All matchups exhausted. Resetting.")
    remaining_matchups = list(all_matchups)


# ============================================================
# CREATE VALID OPPONENT LOOKUP
# ============================================================

valid_opponents = {
    player: set()
    for player in players
}

for p1, p2 in remaining_matchups:

    valid_opponents[p1].add(p2)
    valid_opponents[p2].add(p1)


# ============================================================
# SKILL-BASED MATCHMAKING
# ============================================================

def calculate_matchup_cost(player1, player2):
    """
    The cost of a matchup is the difference
    in number of wins.

    Example:

        Player A = 5 wins
        Player B = 4 wins

        Cost = 1

    Lower cost = better matchup.
    """

    return abs(
        player_wins[player1]
        - player_wins[player2]
    )


def find_best_pairings(players_to_match):
    """
    Finds the combination of pairings that produces
    the smallest total difference in wins.

    This is better than simply matching players
    one at a time because it considers the entire
    round at once.
    """

    player_count = len(players_to_match)

    # Map players to indexes for efficient bitmask operations
    index_to_player = {
        i: player
        for i, player in enumerate(players_to_match)
    }

    player_to_index = {
        player: i
        for i, player in index_to_player.items()
    }

    # --------------------------------------------------------
    # Build valid opponent masks
    # --------------------------------------------------------

    opponent_masks = [
        0
        for _ in range(player_count)
    ]

    for i, player in index_to_player.items():

        for opponent in valid_opponents[player]:

            if opponent in player_to_index:

                opponent_index = player_to_index[
                    opponent
                ]

                opponent_masks[i] |= (
                    1 << opponent_index
                )

    # --------------------------------------------------------
    # Recursive optimization
    # --------------------------------------------------------

    @lru_cache(maxsize=None)
    def solve(mask):

        # Everyone has been matched
        if mask == 0:
            return 0, ()

        # Find the first unmatched player
        first_bit = (
            mask & -mask
        )

        first_index = (
            first_bit.bit_length() - 1
        )

        remaining_mask = (
            mask ^ first_bit
        )

        best_cost = float("inf")
        best_pairings = None

        # Find possible opponents
        opponent_mask = (
            opponent_masks[first_index]
            & remaining_mask
        )

        while opponent_mask:

            opponent_bit = (
                opponent_mask
                & -opponent_mask
            )

            opponent_index = (
                opponent_bit.bit_length() - 1
            )

            opponent_mask ^= opponent_bit

            # Cost of this matchup
            cost = calculate_matchup_cost(
                index_to_player[first_index],
                index_to_player[opponent_index]
            )

            # Solve the rest of the round
            remaining_after_match = (
                remaining_mask
                ^ opponent_bit
            )

            sub_cost, sub_pairings = solve(
                remaining_after_match
            )

            total_cost = (
                cost + sub_cost
            )

            if total_cost < best_cost:

                best_cost = total_cost

                best_pairings = (
                    (
                        index_to_player[first_index],
                        index_to_player[opponent_index]
                    ),
                ) + sub_pairings

        # No valid solution
        if best_pairings is None:

            return float("inf"), ()

        return best_cost, best_pairings

    # Start with every player available
    full_mask = (
        (1 << player_count) - 1
    )

    return solve(full_mask)


# ============================================================
# HANDLE ODD NUMBER OF PLAYERS
# ============================================================

bye_player = None

players_for_pairing = players.copy()

if len(players_for_pairing) % 2 == 1:

    print(
        "\nOdd number of players detected."
    )

    # --------------------------------------------------------
    # Determine the best player to give a bye.
    #
    # We prefer to give the bye to a player where removing
    # them still allows the remaining players to have valid
    # pairings.
    #
    # Among those options, prefer the player with the
    # lowest number of wins.
    # --------------------------------------------------------

    possible_byes = []

    for candidate in players_for_pairing:

        remaining_players = [
            p
            for p in players_for_pairing
            if p != candidate
        ]

        cost, test_pairings = find_best_pairings(
            remaining_players
        )

        if cost != float("inf"):

            possible_byes.append(
                (
                    player_wins[candidate],
                    candidate,
                    cost
                )
            )

    if not possible_byes:

        raise RuntimeError(
            "Unable to create valid pairings for "
            "the current matchup history."
        )

    # Prefer the lowest-ranked player for the bye.
    #
    # If multiple players have the same number of wins,
    # the one resulting in the best overall pairing wins.
    possible_byes.sort(
        key=lambda x: (
            x[0],
            x[2]
        )
    )

    _, bye_player, _ = possible_byes[0]

    players_for_pairing.remove(
        bye_player
    )

    print(
        f"Bye assigned to: "
        f"{bye_player} "
        f"({player_wins[bye_player]} wins)"
    )


# ============================================================
# FIND OPTIMAL PAIRINGS
# ============================================================

total_cost, pairings = find_best_pairings(
    players_for_pairing
)


if total_cost == float("inf"):

    raise RuntimeError(
        "Unable to create a complete set of "
        "non-repeating matchups for this week."
    )


pairings = list(pairings)


# ============================================================
# DISPLAY GENERATED MATCHUPS
# ============================================================

print("\nGenerated Matchups:")
print("-------------------")

for p1, p2 in pairings:

    win_difference = calculate_matchup_cost(
        p1,
        p2
    )

    print(
        f"{p1} "
        f"({player_wins[p1]} wins) "
        f"vs "
        f"{p2} "
        f"({player_wins[p2]} wins) "
        f""
        f"[Difference: {win_difference}]"
    )


print(
    f"\nTotal matchup skill difference: "
    f"{total_cost}"
)


# ============================================================
# CREATE NEW WEEK SHEET
# ============================================================

new_sheet_title = (
    f"Week {next_week}"
)

new_sheet = history_sheet.add_worksheet(
    title=new_sheet_title,
    rows="100",
    cols="4"
)


# ============================================================
# ADD HEADERS
# ============================================================

new_sheet.append_row(
    [
        "Player1",
        "Discord1",
        "Player2",
        "Discord2"
    ]
)


# ============================================================
# ADD MATCHUP ROWS
# ============================================================

rows = []

for p1, p2 in pairings:

    rows.append(
        [
            p1,
            player_to_discord.get(
                p1,
                ""
            ),
            p2,
            player_to_discord.get(
                p2,
                ""
            ),
            ""
        ]
    )


if rows:

    new_sheet.append_rows(
        rows
    )


# ============================================================
# ADD BYE
# ============================================================

if bye_player:

    new_sheet.append_row(
        [
            bye_player,
            player_to_discord.get(
                bye_player,
                ""
            ),
            "BYE",
            "",
            ""
        ]
    )


# ============================================================
# OUTPUT SUMMARY
# ============================================================

print(
    f"\nCreated {new_sheet_title}"
)

print(
    "\nFinal Matchups:"
)

for p1, p2 in pairings:

    print(
        f"{p1} "
        f"({player_to_discord[p1]}, "
        f"{player_wins[p1]} wins)"
        f" vs "
        f"{p2} "
        f"({player_to_discord[p2]}, "
        f"{player_wins[p2]} wins)"
    )


if bye_player:

    print(
        f"\nBye: "
        f"{bye_player} "
        f"({player_wins[bye_player]} wins)"
    )