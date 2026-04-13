from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeamCatalogEntry:
    code: str
    name: str
    conference: str
    players: tuple[str, ...]


TEAM_CATALOG: tuple[TeamCatalogEntry, ...] = (
    TeamCatalogEntry("ATL", "Atlanta Hawks", "East", ("Keshon Gilbert", "RayJ Dennis", "Keaton Wallace", "CJ McCollum", "Gabe Vincent", "Dyson Daniels", "Nickeil Alexander-Walker", "Buddy Hield", "Jonathan Kuminga", "Jalen Johnson", "Zaccharie Risacher", "Asa Newell", "Mouhamed Gueye", "Corey Kispert", "Christian Koloko", "Tony Bradley", "Onyeka Okongwu", "Jock Landale")),
    TeamCatalogEntry("BKN", "Brooklyn Nets", "East", ("Cam Thomas", "Mikal Bridges", "Cameron Johnson", "Nic Claxton", "Dorian Finney-Smith", "Dennis Schroder", "Noah Clowney", "Trendon Watford")),
    TeamCatalogEntry("BOS", "Boston Celtics", "East", ("Jayson Tatum", "Nikola Vucevic", "Jaylen Brown", "John Tonje", "Derrick White", "Payton Pritchard", "Ron Harper Jr.", "Jordan Walsh", "Hugo Gonzalez", "Sam Hauser", "Max Shulga", "Dalano Banton", "Luka Garza", "Baylor Scheierman", "Amari Williams", "Neemias Queta")),
    TeamCatalogEntry("CHA", "Charlotte Hornets", "East", ("Miles Bridges", "LaMelo Ball", "Grant Williams", "Coby White", "Sion James", "Kon Knueppel", "Josh Green", "Ryan Kalkbrenner", "Antonio Reeves", "Moussa Diabate", "PJ Hall", "Tosan Evbuomwan", "Pat Connaughton", "Tre Mann", "Brandon Miller", "Xavier Tillman", "Tidjane Salaun", "Liam McNeeley")),
    TeamCatalogEntry("CHI", "Chicago Bulls", "East", ("Coby White", "Ayo Dosunmu", "Nikola Vucevic", "Josh Giddey", "Patrick Williams", "Lonzo Ball", "Julian Phillips", "Jevon Carter")),
    TeamCatalogEntry("CLE", "Cleveland Cavaliers", "East", ("James Harden", "Max Strus", "Thomas Bryant", "Evan Mobley", "Sam Merrill", "Dennis Schroder", "Craig Porter Jr.", "Riley Minix", "Keon Ellis", "Jaylon Tyson", "Tristan Enaruna", "Larry Nance Jr.", "Tyrese Proctor", "Jarrett Allen", "Dean Wade", "Olivier Sarr", "Nae'Qwan Tomlin", "Donovan Mitchell")),
    TeamCatalogEntry("DET", "Detroit Pistons", "East", ("Jalen Duren", "Cade Cunningham", "Isaac Jones", "Ronald Holland II", "Paul Reed", "Caris LeVert", "Ausar Thompson", "Tobias Harris", "Wendell Moore Jr.", "Chaz Lanier", "Daniss Jenkins", "Marcus Sasser", "Kevin Huerter", "Isaiah Stewart", "Javonte Green", "Tolu Smith", "Duncan Robinson")),
    TeamCatalogEntry("IND", "Indiana Pacers", "East", ("Tyrese Haliburton", "Pascal Siakam", "Myles Turner", "Andrew Nembhard", "Bennedict Mathurin", "Aaron Nesmith", "T.J. McConnell", "Obi Toppin")),
    TeamCatalogEntry("MIA", "Miami Heat", "East", ("Simone Fontecchio", "Trevor Keels", "Nikola Jovic", "Kel'el Ware", "Pelle Larsson", "Jaime Jaquez Jr.", "Dru Smith", "Bam Adebayo", "Tyler Herro", "Myron Gardner", "Keshad Johnson", "Jahmir Young", "Andrew Wiggins", "Norman Powell", "Kasparas Jakucionis", "Davion Mitchell", "Vladislav Goldin")),
    TeamCatalogEntry("MIL", "Milwaukee Bucks", "East", ("Giannis Antetokounmpo", "Damian Lillard", "Khris Middleton", "Brook Lopez", "Bobby Portis", "Malik Beasley", "Pat Connaughton", "AJ Green")),
    TeamCatalogEntry("NYK", "New York Knicks", "East", ("Jordan Clarkson", "Miles McBride", "Josh Hart", "Pacome Dadiet", "Jose Alvarado", "OG Anunoby", "Kevin McCullar Jr.", "Jalen Brunson", "Tyler Kolek", "Jeremy Sochan", "Mitchell Robinson", "Mikal Bridges", "Karl-Anthony Towns", "Dillon Jones", "Landry Shamet", "Trey Jemison III", "Mohamed Diawara", "Ariel Hukporti")),
    TeamCatalogEntry("ORL", "Orlando Magic", "East", ("Alex Morales", "Anthony Black", "Jonathan Isaac", "Jevon Carter", "Desmond Bane", "Jalen Suggs", "Paolo Banchero", "Jamal Cain", "Jase Richardson", "Jett Howard", "Colin Castleton", "Moritz Wagner", "Franz Wagner", "Tristan da Silva", "Wendell Carter Jr.", "Goga Bitadze", "Noah Penda")),
    TeamCatalogEntry("PHI", "Philadelphia 76ers", "East", ("Tyrese Maxey", "Andre Drummond", "Quentin Grimes", "Kyle Lowry", "Paul George", "Kelly Oubre Jr.", "Justin Edwards", "Trendon Watford", "Dalen Terry", "MarJon Beauchamp", "Joel Embiid", "Johni Broome", "Tyrese Martin", "Dominick Barlow", "Adem Bona", "Jabari Walker", "VJ Edgecombe")),
    TeamCatalogEntry("TOR", "Toronto Raptors", "East", ("A.J. Lawson", "Gradey Dick", "Jonathan Mogbo", "Brandon Ingram", "Scottie Barnes", "Immanuel Quickley", "RJ Barrett", "Collin Murray-Boyles", "Ja'Kobe Walter", "Garrett Temple", "Jakob Poeltl", "Jamal Shead", "Chucky Hepburn", "Trayce Jackson-Davis", "Sandro Mamukelashvili", "Alijah Martin", "Jamison Battle")),
    TeamCatalogEntry("WAS", "Washington Wizards", "East", ("Jordan Poole", "Kyle Kuzma", "Bilal Coulibaly", "Alex Sarr", "Malcolm Brogdon", "Corey Kispert", "Jonas Valanciunas", "Bub Carrington")),
    TeamCatalogEntry("DAL", "Dallas Mavericks", "West", ("Luka Doncic", "Kyrie Irving", "Klay Thompson", "P.J. Washington", "Dereck Lively II", "Daniel Gafford", "Naji Marshall", "Maxi Kleber")),
    TeamCatalogEntry("DEN", "Denver Nuggets", "West", ("Christian Braun", "Curtis Jones", "Julian Strawther", "Tyus Jones", "Peyton Watson", "Tim Hardaway Jr.", "Bruce Brown", "DaRon Holmes II", "Nikola Jokic", "Jonas Valanciunas", "Spencer Jones", "Zeke Nnaji", "Cameron Johnson", "Jalen Pickett", "KJ Simpson", "Jamal Murray", "Aaron Gordon", "David Roddy")),
    TeamCatalogEntry("GSW", "Golden State Warriors", "West", ("Gary Payton II", "Brandin Podziemski", "Will Richard", "Moses Moody", "Kristaps Porzingis", "De'Anthony Melton", "Jimmy Butler III", "Gui Santos", "LJ Cryer", "Nate Williams", "Al Horford", "Quinten Post", "Draymond Green", "Charles Bassey", "Stephen Curry", "Seth Curry", "Malevy Leons", "Pat Spencer")),
    TeamCatalogEntry("HOU", "Houston Rockets", "West", ("Aaron Holiday", "Amen Thompson", "Dorian Finney-Smith", "JD Davison", "Fred VanVleet", "Kevin Durant", "Jae'Sean Tate", "Jabari Smith Jr.", "Steven Adams", "Tristen Newton", "Reed Sheppard", "Tari Eason", "Josh Okogie", "Isaiah Crawford", "Alperen Sengun", "Clint Capela", "Jeff Green")),
    TeamCatalogEntry("LAC", "Los Angeles Clippers", "West", ("Norchad Omier", "Sean Pedulla", "Bradley Beal", "Kawhi Leonard", "Kobe Sanders", "Derrick Jones Jr.", "Bogdan Bogdanovic", "Kris Dunn", "Bennedict Mathurin", "Darius Garland", "Brook Lopez", "Cam Christie", "TyTy Washington Jr.", "Yanic Konan Niederhauser", "John Collins", "Jordan Miller", "Isaiah Jackson", "Nicolas Batum")),
    TeamCatalogEntry("LAL", "Los Angeles Lakers", "West", ("Adou Thiero", "Jarred Vanderbilt", "Dalton Knecht", "Deandre Ayton", "Bronny James", "Luke Kennard", "Jaxson Hayes", "Jake LaRavia", "Maxi Kleber", "Austin Reaves", "Drew Timme", "Nick Smith Jr.", "LeBron James", "Rui Hachimura", "Chris Manon", "Marcus Smart", "Luka Doncic")),
    TeamCatalogEntry("MEM", "Memphis Grizzlies", "West", ("Ja Morant", "Jaren Jackson Jr.", "Desmond Bane", "Marcus Smart", "Zach Edey", "Santi Aldama", "Brandon Clarke", "Scotty Pippen Jr.")),
    TeamCatalogEntry("MIN", "Minnesota Timberwolves", "West", ("Donte DiVincenzo", "Terrence Shannon Jr.", "Jaden McDaniels", "Julian Phillips", "Anthony Edwards", "Joe Ingles", "Bones Hyland", "Mike Conley", "Naz Reid", "Kyle Anderson", "Ayo Dosunmu", "Zyon Pullin", "Joan Beringer", "Jaylen Clark", "Enrique Freeman", "Rudy Gobert", "Julius Randle", "Rocco Zikarsky")),
    TeamCatalogEntry("NOP", "New Orleans Pelicans", "West", ("Zion Williamson", "Brandon Ingram", "CJ McCollum", "Trey Murphy III", "Herbert Jones", "Yves Missi", "Jose Alvarado", "Jordan Hawkins")),
    TeamCatalogEntry("OKC", "Oklahoma City Thunder", "West", ("Shai Gilgeous-Alexander", "Jared McCain", "Luguentz Dort", "Jaylin Williams", "Chet Holmgren", "Jalen Williams", "Alex Caruso", "Isaiah Joe", "Thomas Sorber", "Payton Sandfort", "Branden Carlson", "Aaron Wiggins", "Cason Wallace", "Brooks Barnhizer", "Ajay Mitchell", "Kenrich Williams", "Nikola Topic", "Isaiah Hartenstein")),
    TeamCatalogEntry("PHX", "Phoenix Suns", "West", ("Royce O'Neale", "Ryan Dunn", "Devin Booker", "Amir Coffey", "Dillon Brooks", "Jalen Green", "Haywood Highsmith", "Grayson Allen", "Khaman Maluach", "Oso Ighodaro", "Collin Gillespie", "Koby Brea", "Mark Williams", "Jamaree Bouyea", "Isaiah Livers", "Rasheer Fleming", "CJ Huntley", "Jordan Goodwin")),
    TeamCatalogEntry("POR", "Portland Trail Blazers", "West", ("Jayson Kent", "Scoot Henderson", "Damian Lillard", "Blake Wesley", "Caleb Love", "Chris Youngblood", "Matisse Thybulle", "Jrue Holiday", "Deni Avdija", "Jerami Grant", "Yang Hansen", "Shaedon Sharpe", "Donovan Clingan", "Kris Murray", "Vit Krejci", "Toumani Camara", "Robert Williams III", "Sidy Cissoko")),
    TeamCatalogEntry("SAC", "Sacramento Kings", "West", ("De'Aaron Fox", "Domantas Sabonis", "DeMar DeRozan", "Keegan Murray", "Malik Monk", "Kevin Huerter", "Keon Ellis", "Trey Lyles")),
    TeamCatalogEntry("SAS", "San Antonio Spurs", "West", ("Jordan McLaughlin", "Dylan Harper", "De'Aaron Fox", "Stephon Castle", "David Jones Garcia", "Keldon Johnson", "Devin Vassell", "Julian Champagnie", "Harrison Barnes", "Harrison Ingram", "Lindy Waters III", "Emanuel Miller", "Carter Bryant", "Victor Wembanyama", "Luke Kornet", "Kelly Olynyk", "Bismack Biyombo", "Mason Plumlee")),
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
