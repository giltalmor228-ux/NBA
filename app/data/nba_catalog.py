from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeamCatalogEntry:
    code: str
    name: str
    conference: str
    players: tuple[str, ...]


TEAM_CATALOG: tuple[TeamCatalogEntry, ...] = (
    TeamCatalogEntry("ATL", "Atlanta Hawks", "East", ("Trae Young", "Dyson Daniels", "Zaccharie Risacher", "Jalen Johnson", "Onyeka Okongwu", "Clint Capela", "Bogdan Bogdanovic", "De'Andre Hunter")),
    TeamCatalogEntry("BKN", "Brooklyn Nets", "East", ("Cam Thomas", "Mikal Bridges", "Cameron Johnson", "Nic Claxton", "Dorian Finney-Smith", "Dennis Schroder", "Noah Clowney", "Trendon Watford")),
    TeamCatalogEntry("BOS", "Boston Celtics", "East", ("Jayson Tatum", "Jaylen Brown", "Kristaps Porzingis", "Jrue Holiday", "Derrick White", "Payton Pritchard", "Al Horford", "Sam Hauser")),
    TeamCatalogEntry("CHA", "Charlotte Hornets", "East", ("LaMelo Ball", "Brandon Miller", "Miles Bridges", "Mark Williams", "Tre Mann", "Grant Williams", "Nick Smith Jr.", "Josh Green")),
    TeamCatalogEntry("CHI", "Chicago Bulls", "East", ("Coby White", "Ayo Dosunmu", "Nikola Vucevic", "Josh Giddey", "Patrick Williams", "Lonzo Ball", "Julian Phillips", "Jevon Carter")),
    TeamCatalogEntry("CLE", "Cleveland Cavaliers", "East", ("Donovan Mitchell", "Darius Garland", "Evan Mobley", "Jarrett Allen", "Max Strus", "Caris LeVert", "Isaac Okoro", "Sam Merrill")),
    TeamCatalogEntry("DET", "Detroit Pistons", "East", ("Cade Cunningham", "Jaden Ivey", "Ausar Thompson", "Jalen Duren", "Tobias Harris", "Marcus Sasser", "Simone Fontecchio", "Isaiah Stewart")),
    TeamCatalogEntry("IND", "Indiana Pacers", "East", ("Tyrese Haliburton", "Pascal Siakam", "Myles Turner", "Andrew Nembhard", "Bennedict Mathurin", "Aaron Nesmith", "T.J. McConnell", "Obi Toppin")),
    TeamCatalogEntry("MIA", "Miami Heat", "East", ("Jimmy Butler", "Bam Adebayo", "Tyler Herro", "Terry Rozier", "Jaime Jaquez Jr.", "Duncan Robinson", "Nikola Jovic", "Kevin Love")),
    TeamCatalogEntry("MIL", "Milwaukee Bucks", "East", ("Giannis Antetokounmpo", "Damian Lillard", "Khris Middleton", "Brook Lopez", "Bobby Portis", "Malik Beasley", "Pat Connaughton", "AJ Green")),
    TeamCatalogEntry("NYK", "New York Knicks", "East", ("Jalen Brunson", "Karl-Anthony Towns", "OG Anunoby", "Mikal Bridges", "Josh Hart", "Mitchell Robinson", "Donte DiVincenzo", "Miles McBride")),
    TeamCatalogEntry("ORL", "Orlando Magic", "East", ("Paolo Banchero", "Franz Wagner", "Jalen Suggs", "Wendell Carter Jr.", "Jonathan Isaac", "Cole Anthony", "Anthony Black", "Moritz Wagner")),
    TeamCatalogEntry("PHI", "Philadelphia 76ers", "East", ("Joel Embiid", "Tyrese Maxey", "Paul George", "Kelly Oubre Jr.", "Caleb Martin", "Andre Drummond", "Jared McCain", "Eric Gordon")),
    TeamCatalogEntry("TOR", "Toronto Raptors", "East", ("Scottie Barnes", "RJ Barrett", "Immanuel Quickley", "Jakob Poeltl", "Gradey Dick", "Ochai Agbaji", "Kelly Olynyk", "Bruce Brown")),
    TeamCatalogEntry("WAS", "Washington Wizards", "East", ("Jordan Poole", "Kyle Kuzma", "Bilal Coulibaly", "Alex Sarr", "Malcolm Brogdon", "Corey Kispert", "Jonas Valanciunas", "Bub Carrington")),
    TeamCatalogEntry("DAL", "Dallas Mavericks", "West", ("Luka Doncic", "Kyrie Irving", "Klay Thompson", "P.J. Washington", "Dereck Lively II", "Daniel Gafford", "Naji Marshall", "Maxi Kleber")),
    TeamCatalogEntry("DEN", "Denver Nuggets", "West", ("Nikola Jokic", "Jamal Murray", "Michael Porter Jr.", "Aaron Gordon", "Christian Braun", "Russell Westbrook", "Peyton Watson", "Julian Strawther")),
    TeamCatalogEntry("GSW", "Golden State Warriors", "West", ("Stephen Curry", "Draymond Green", "Jonathan Kuminga", "Andrew Wiggins", "Brandin Podziemski", "Moses Moody", "Buddy Hield", "Kevon Looney")),
    TeamCatalogEntry("HOU", "Houston Rockets", "West", ("Alperen Sengun", "Jalen Green", "Fred VanVleet", "Amen Thompson", "Jabari Smith Jr.", "Dillon Brooks", "Cam Whitmore", "Reed Sheppard")),
    TeamCatalogEntry("LAC", "Los Angeles Clippers", "West", ("Kawhi Leonard", "James Harden", "Norman Powell", "Ivica Zubac", "Terance Mann", "Kris Dunn", "Amir Coffey", "Nicolas Batum")),
    TeamCatalogEntry("LAL", "Los Angeles Lakers", "West", ("LeBron James", "Anthony Davis", "Austin Reaves", "Rui Hachimura", "D'Angelo Russell", "Jarred Vanderbilt", "Dalton Knecht", "Gabe Vincent")),
    TeamCatalogEntry("MEM", "Memphis Grizzlies", "West", ("Ja Morant", "Jaren Jackson Jr.", "Desmond Bane", "Marcus Smart", "Zach Edey", "Santi Aldama", "Brandon Clarke", "Scotty Pippen Jr.")),
    TeamCatalogEntry("MIN", "Minnesota Timberwolves", "West", ("Anthony Edwards", "Julius Randle", "Rudy Gobert", "Naz Reid", "Jaden McDaniels", "Mike Conley", "Donte DiVincenzo", "Nickeil Alexander-Walker")),
    TeamCatalogEntry("NOP", "New Orleans Pelicans", "West", ("Zion Williamson", "Brandon Ingram", "CJ McCollum", "Trey Murphy III", "Herbert Jones", "Yves Missi", "Jose Alvarado", "Jordan Hawkins")),
    TeamCatalogEntry("OKC", "Oklahoma City Thunder", "West", ("Shai Gilgeous-Alexander", "Chet Holmgren", "Jalen Williams", "Isaiah Hartenstein", "Luguentz Dort", "Alex Caruso", "Cason Wallace", "Aaron Wiggins")),
    TeamCatalogEntry("PHX", "Phoenix Suns", "West", ("Kevin Durant", "Devin Booker", "Bradley Beal", "Grayson Allen", "Jusuf Nurkic", "Tyus Jones", "Royce O'Neale", "Bol Bol")),
    TeamCatalogEntry("POR", "Portland Trail Blazers", "West", ("Anfernee Simons", "Scoot Henderson", "Shaedon Sharpe", "Jerami Grant", "Deandre Ayton", "Deni Avdija", "Toumani Camara", "Robert Williams III")),
    TeamCatalogEntry("SAC", "Sacramento Kings", "West", ("De'Aaron Fox", "Domantas Sabonis", "DeMar DeRozan", "Keegan Murray", "Malik Monk", "Kevin Huerter", "Keon Ellis", "Trey Lyles")),
    TeamCatalogEntry("SAS", "San Antonio Spurs", "West", ("Victor Wembanyama", "De'Aaron Fox", "Stephon Castle", "Devin Vassell", "Jeremy Sochan", "Chris Paul", "Keldon Johnson", "Harrison Barnes")),
    TeamCatalogEntry("UTA", "Utah Jazz", "West", ("Lauri Markkanen", "Keyonte George", "Collin Sexton", "Walker Kessler", "Jordan Clarkson", "John Collins", "Taylor Hendricks", "Isaiah Collier")),
)


TEAM_BY_CODE = {team.code: team for team in TEAM_CATALOG}


def teams_by_conference() -> dict[str, list[TeamCatalogEntry]]:
    grouped = {"East": [], "West": []}
    for team in TEAM_CATALOG:
        grouped[team.conference].append(team)
    for conference in grouped:
        grouped[conference] = sorted(grouped[conference], key=lambda item: item.name)
    return grouped


def all_teams_grouped_for_select() -> list[tuple[str, list[TeamCatalogEntry]]]:
    grouped = teams_by_conference()
    return [("East", grouped["East"]), ("West", grouped["West"])]


def players_for_teams(team_codes: list[str]) -> list[str]:
    seen: set[str] = set()
    players: list[str] = []
    for code in team_codes:
        team = TEAM_BY_CODE.get(code.upper())
        if not team:
            continue
        for player in team.players:
            if player not in seen:
                seen.add(player)
                players.append(player)
    return players
