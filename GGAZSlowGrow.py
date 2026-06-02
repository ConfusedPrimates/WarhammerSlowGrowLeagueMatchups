import gspread
from oauth2client.service_account import ServiceAccountCredentials
import random
from itertools import combinations
import re
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition

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
players_sheet = client.open("Gamers Guild AZ Tempe: Warhammer The Old World League Roster").sheet1
history_sheet = client.open("Slow Grow League Match Ups")

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

# -----------------------------
# GENERATE MATCHUPS
# -----------------------------
all_matchups = set(tuple(sorted(pair)) for pair in combinations(players, 2))
remaining_matchups = list(all_matchups - past_matchups)

# Reset if needed
if not remaining_matchups:
    print("All matchups exhausted. Resetting.")
    remaining_matchups = list(all_matchups)

random.shuffle(players)

pairings = []
used_players = set()

for p1 in players:
    if p1 in used_players:
        continue

    for p2 in players:
        if p1 == p2 or p2 in used_players:
            continue

        pair = tuple(sorted([p1, p2]))

        if pair in remaining_matchups:
            pairings.append(pair)
            used_players.add(p1)
            used_players.add(p2)
            break

# Handle odd player
bye_player = None
if len(players) % 2 == 1:
    for p in players:
        if p not in used_players:
            bye_player = p
            break

# -----------------------------
# CREATE NEW WEEK SHEET
# -----------------------------
new_sheet_title = f"Week {next_week}"
new_sheet = history_sheet.add_worksheet(title=new_sheet_title, rows="100", cols="4")

# Add headers
new_sheet.append_row(["Player1", "Discord1", "Player2", "Discord2", "Result"])

# Rows
rows = []
for p1, p2 in pairings:
    rows.append([
        p1,
        player_to_discord.get(p1, ""),
        p2,
        player_to_discord.get(p2, ""),
        "" # Result column
    ])

if rows:
    new_sheet.append_rows(rows)

# Bye row
if bye_player:
    new_sheet.append_row([
        bye_player,
        player_to_discord.get(bye_player, ""),
        "BYE",
        ""
    ])

# Apply dropdown per row
for i, (p1, p2) in enumerate(pairings, start=2):  # start=2 because row 1 is header
    
    rule = DataValidationRule(
        BooleanCondition(
            'ONE_OF_LIST',
            [p1 + ' Crushing victory',p1 +' victory', p2 + ' Crushing victory', p2 + ' victory', 'Draw']
        ),
        showCustomUi=True
    )
    
    cell_range = f"E{i}"
    set_data_validation_for_cell_range(new_sheet, cell_range, rule)

# -----------------------------
# OUTPUT
# -----------------------------
print(f"\nCreated {new_sheet_title}")
for p1, p2 in pairings:
    print(f"{p1} ({player_to_discord[p1]}) vs {p2} ({player_to_discord[p2]})")

if bye_player:
    print(f"Bye: {bye_player}")