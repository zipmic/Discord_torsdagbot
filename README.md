# TorsdagBot 🗓️

En lille Discord-bot der **hver torsdag kl. 15:00 dansk tid** automatisk opretter en afstemning i en valgt kanal:

> @everyone Det er torsdag!
>
> **Hvornår kommer du online i aften?**
>
> - 🕖 Early Bird kl. 19:00–20:00
> - 🕗 Mellem kl. 20:00–20:30
> - 🕣 Mellem kl. 20:30–21:00
> - 🕘 Efter 21:00 lol
> - 🕙 Efter 22:00 lol
> - ❌ Jeg kommer ikke

Den øverste linje **skifter automatisk fra torsdag til torsdag** – der er 16 forskellige at rotere mellem, se [Torsdagsbeskederne](#torsdagsbeskederne).

Svarmulighederne "Efter 21:00" og "Efter 22:00" har jeres egne server-emojis (`:code:` og `:clue:`) sat på som standard – se [Server-emojis](#server-emojis).

Botten er skrevet i Python med [discord.py](https://discordpy.readthedocs.io/) og kan pakkes til en enkelt `TorsdagBot.exe`, der kan køre på en almindelig Windows-computer.

> 🆕 **Torsdagsbar-statistik.** Botten registrerer også, hvor længe folk sidder i voicechat under torsdagsbaren (torsdag 19:00 → fredag 03:00), sender en opsummering hver fredag kl. 12:00 med **aftenens titler** (👑 Aftenens konge, 🏃 Marathonmand, ⚡ Speedrun, 🤥 Store ord …), driller dem der **kommer for sent**, og har **årsopdelt statistik**, **citat-bog** og **profilkort**. Funktionen er **valgfri** og påvirker ikke afstemningen. Se **[Torsdagsbar-statistik](#torsdagsbar--voice-registrering-og-statistik)**.

---

## Indhold

1. [Hvad kan botten?](#hvad-kan-botten)
2. [Filer i projektet](#filer-i-projektet)
3. [Trin 1 – Opret en Discord-applikation og en bot](#trin-1--opret-en-discord-applikation-og-en-bot)
4. [Trin 2 – Kopiér bottens token](#trin-2--kopiér-bottens-token)
5. [Trin 3 – Intents](#trin-3--intents)
6. [Trin 4 – Inviter botten til serveren](#trin-4--inviter-botten-til-serveren)
7. [Trin 5 – Rettigheder (permissions)](#trin-5--rettigheder-permissions)
8. [Trin 6 – Slå Developer Mode til](#trin-6--slå-developer-mode-til)
9. [Trin 7 – Kopiér kanalens ID (og dit eget bruger-ID)](#trin-7--kopiér-kanalens-id-og-dit-eget-bruger-id)
10. [Trin 8 – Opret `.env`-filen](#trin-8--opret-env-filen)
11. [Trin 9 – Test botten uden at vente til torsdag](#trin-9--test-botten-uden-at-vente-til-torsdag)
12. [Trin 10 – Byg `.exe`-filen](#trin-10--byg-exe-filen)
13. [Trin 11 – Start automatisk når Windows starter](#trin-11--start-automatisk-når-windows-starter)
14. [Trin 12 – Vigtigt: computeren skal være tændt](#trin-12--vigtigt-computeren-skal-være-tændt)
15. [Alle indstillinger](#alle-indstillinger)
16. [Torsdagsbeskederne](#torsdagsbeskederne)
17. [Server-emojis](#server-emojis)
18. [Torsdagsbar – voice-registrering og statistik](#torsdagsbar--voice-registrering-og-statistik)
19. [Fejlfinding](#fejlfinding)

---

## Hvad kan botten?

- ✅ Sender afstemningen **automatisk hver torsdag kl. 15:00** i tidszonen `Europe/Copenhagen` (sommer-/vintertid håndteres automatisk).
- ✅ **Skifter besked hver torsdag** – 16 forskellige tekster på rotation, så det ikke bliver den samme sætning hver uge.
- ✅ Sender **kun én afstemning pr. torsdag** – også hvis du genstarter programmet 10 gange. Datoen gemmes i `poll_state.json`.
- ✅ Virker uanset om programmet startes **før**, **under** eller **efter** kl. 15:00 om torsdagen.
- ✅ Bruger **Discords indbyggede poll-funktion** (discord.py 2.5+). Kan ikke den bruges, skifter botten automatisk til **knapper med persistente Views**.
- ✅ Knapper: alle kan stemme, hver person har **ét aktivt svar**, man kan **skifte svar**, **stemmetallene vises i beskeden**, stemmerne **gemmes lokalt** og **knapperne virker stadig efter en genstart**.
- ✅ Ejerbeskyttet testkommando **`/testvote`**.
- ✅ **`/erdettorsdag`** – livets vigtigste spørgsmål. Svarer `:D` + et billede om torsdagen, og `:(` + et andet billede alle andre dage. Læg dine egne billeder i undermappen **`imgs`** ved siden af `.exe`-filen som `torsdag.jpg` og `ikke_torsdag.jpg` (jpg/png/gif/webp) — så bruges de. Findes de ikke, henter botten i stedet billederne fra [erdettorsdag.dk](https://erdettorsdag.dk).
- ✅ Tydelig logning i konsollen og i `torsdagbot.log`.
- ✅ **Automatisk genforbindelse** hvis internettet eller Discord falder ud.
- ✅ Tokenet står **aldrig** i kildekoden – kun i `.env`.
- ✅ **Torsdagsbar-statistik** (valgfri): voice-registrering, årsopdelt statistik, streaks, rekorder, aftentitler i fredagsopsummeringen, "du er sent på den"-opsang, citat-bog og profilkort.

---

## Filer i projektet

| Fil | Hvad den gør |
|---|---|
| `bot.py` | Hovedprogrammet (afstemning + kobler torsdagsbaren på) |
| `torsdagsbar/` | Pakke med voice-registrering og statistik (database, tracker, kommandoer) |
| `tests/` | Automatiske tests |
| `requirements.txt` | Python-pakker der skal installeres |
| `.env.example` | Skabelon til dine indstillinger – **kopiér den til `.env`** |
| `config.example.json` | Valgfrit alternativ til `.env` (undtagen tokenet) + torsdagsbar-indstillinger |
| `build.bat` | Bygger `dist\TorsdagBot.exe` |
| `start_bot.bat` | Starter botten (og genstarter den hvis den lukker) |
| `README.md` | Denne vejledning |

Filer der **oprettes automatisk**, når botten kører:

| Fil | Hvad den indeholder |
|---|---|
| `poll_state.json` | Datoen for den seneste afstemning, hvor langt beskedrotationen er nået, + de afgivne stemmer |
| `torsdagsbar.db` | SQLite-database med al voice-deltagelse (kun hvis torsdagsbaren er slået til) |
| `torsdagbot.log` | Log over hvad botten har lavet |

> 📁 **Vigtigt:** `.env`, `config.json`, `poll_state.json`, `torsdagsbar.db` og `torsdagbot.log` skal ligge i **samme mappe som `TorsdagBot.exe`** – ikke i den mappe, du tilfældigvis står i, når du starter programmet. Botten finder selv filerne ud fra placeringen af `.exe`-filen.

---

## Trin 1 – Opret en Discord-applikation og en bot

1. Gå til **<https://discord.com/developers/applications>** og log ind med din Discord-konto.
2. Klik på **New Application** øverst til højre.
3. Giv den et navn (fx `TorsdagBot`), sæt flueben i vilkårene og klik **Create**.
4. Klik på **Bot** i menuen til venstre.
5. Klik eventuelt **Add Bot** / **Reset Token** hvis botten ikke allerede findes.
6. Du kan give botten et brugernavn og et profilbillede under **Bot**.

---

## Trin 2 – Kopiér bottens token

1. Stadig under **Bot** → find feltet **Token**.
2. Klik **Reset Token** → **Yes, do it!** → **Copy**.
3. Tokenet vises **kun én gang**. Sæt det ind i `.env` med det samme (se [Trin 8](#trin-8--opret-env-filen)).

> ⚠️ **Del aldrig dit token med nogen, og læg det aldrig på GitHub.**
> Har du ved et uheld delt det, så klik **Reset Token** igen – det gamle bliver ugyldigt.

---

## Trin 3 – Intents

Botten bruger **ingen privilegerede intents**. Den læser ikke beskeder – den sender kun beskeder og modtager knaptryk og slash-kommandoer.

Under **Bot → Privileged Gateway Intents** kan alle tre stå **slået fra**:

| Intent | Skal den være tændt? |
|---|---|
| Presence Intent | ❌ Nej |
| Server Members Intent | ❌ Nej |
| **Message Content Intent** | ❌ **Nej** |

Botten bruger kun standard-intents (`discord.Intents.default()`), som ikke kræver godkendelse.

Under **Bot → Bot Permissions** kan du desuden lade **Public Bot** stå slået fra, hvis kun du skal kunne invitere botten.

---

## Trin 4 – Inviter botten til serveren

1. Gå til **OAuth2 → URL Generator** i venstremenuen.
2. Under **Scopes** sæt flueben ved:
   - ✅ `bot`
   - ✅ `applications.commands`  ← nødvendig for at `/testvote` virker
3. Under **Bot Permissions** sæt flueben ved rettighederne fra [Trin 5](#trin-5--rettigheder-permissions).
4. Kopiér den **Generated URL** nederst på siden.
5. Åbn linket i browseren, vælg din server og klik **Godkend / Authorize**.

> Du skal have rettigheden **Administrer server (Manage Server)** på serveren for at kunne invitere en bot.

---

## Trin 5 – Rettigheder (permissions)

Botten skal have disse rettigheder – både på serveren **og** i den kanal, afstemningen sendes i:

| Rettighed (dansk) | Rettighed (engelsk) | Hvorfor |
|---|---|---|
| Vis kanal | View Channel | For at kunne se kanalen |
| Send beskeder | Send Messages | For at sende afstemningen |
| Indlejre links | Embed Links | For at vise stemmetallene pænt |
| **Nævn @everyone, @here og alle roller** | **Mention Everyone** | For at `@everyone` giver en notifikation |
| Læs beskedhistorik | Read Message History | For at kunne opdatere afstemningen |
| Tilføj reaktioner | Add Reactions | Kun hvis du selv vil bruge reaktioner |

De ovenstående flueben svarer til permissions-tallet **`274878123072`**. Du kan også bare indsætte din applikations **Application ID** (findes under **General Information**) i dette link:

```
https://discord.com/oauth2/authorize?client_id=DIT_APPLICATION_ID&scope=bot+applications.commands&permissions=274878123072
```

**Tjek også kanalens egne indstillinger:** højreklik på kanalen → **Rediger kanal → Tilladelser**. Hvis kanalen har særlige tilladelser, skal bottens rolle have `Send beskeder` og `Nævn @everyone` her også. Kanalindstillinger overtrumfer serverindstillinger.

> Botten skriver en advarsel i loggen, hvis den mangler `Mention Everyone` – så sendes beskeden stadig, men uden ping.

---

## Trin 6 – Slå Developer Mode til

For at kunne kopiere ID'er skal Developer Mode være slået til i Discord-appen:

1. Klik på **tandhjulet** ⚙️ nede ved dit brugernavn (**Brugerindstillinger**).
2. Vælg **Avanceret** (Advanced) i menuen til venstre.
3. Slå **Udviklertilstand / Developer Mode** til.

---

## Trin 7 – Kopiér kanalens ID (og dit eget bruger-ID)

**Kanal-ID (`CHANNEL_ID`):**

1. Højreklik på den tekstkanal, afstemningen skal sendes i.
2. Vælg **Kopiér kanal-ID** (Copy Channel ID) nederst i menuen.
3. Du har nu et langt tal i udklipsholderen, fx `1122334455667788990`.

**Dit eget bruger-ID (`OWNER_ID`):**

1. Højreklik på dit eget navn i medlemslisten eller i en besked.
2. Vælg **Kopiér bruger-ID** (Copy User ID).

**Server-ID (`GUILD_ID`, valgfrit men anbefalet):**

1. Højreklik på serverikonet yderst til venstre.
2. Vælg **Kopiér server-ID** (Copy Server ID).
   Sætter du dette, bliver `/testvote` synlig i Discord **med det samme** i stedet for op til en time senere.

---

## Trin 8 – Opret `.env`-filen

1. Find filen **`.env.example`**.
2. Lav en kopi af den og omdøb kopien til **`.env`** (præcis sådan – med punktum foran og uden `.txt` til sidst).
3. Åbn `.env` i Notesblok og udfyld:

```
DISCORD_TOKEN=indsæt_token_her
CHANNEL_ID=indsæt_kanal_id_her
OWNER_ID=indsæt_dit_bruger_id_her
```

Et udfyldt eksempel:

```
DISCORD_TOKEN=MTIzNDU2Nzg5MDEyMzQ1Njc4.GaBcDe.eksempel-token-udskift-mig
CHANNEL_ID=1122334455667788990
OWNER_ID=9988776655443322110
GUILD_ID=1000000000000000000
```

> 💡 **Windows skjuler filtypen.** Hvis din fil kommer til at hedde `.env.txt`, virker den ikke.
> Slå **Filtypenavne** til under fanen **Vis** i Stifinder, eller gem filen fra Notesblok med `"..env"` i anførselstegn og filtypen `Alle filer`.

**`.env`-filen skal ligge i samme mappe som `TorsdagBot.exe`** (dvs. i `dist`-mappen efter en build). Når du kører kildekoden i stedet, skal den ligge ved siden af `bot.py`.

**Alternativ:** Alt undtagen tokenet kan i stedet stå i en `config.json` ved siden af `.exe`-filen – se `config.example.json`. Tokenet læses **kun** fra `.env` (eller en rigtig miljøvariabel).

---

## Trin 9 – Test botten uden at vente til torsdag

### Kør botten fra kildekoden

```bat
python -m pip install -r requirements.txt
python bot.py
```

eller dobbeltklik på **`start_bot.bat`**.

I konsollen skal du se noget i stil med:

```
TorsdagBot v1.0.0 starter
Programmappe: C:\Users\dig\TorsdagBot
Læste indstillinger fra C:\Users\dig\TorsdagBot\.env
Konfiguration OK · kanal-ID: 1122... · ejer-ID: 9988... · tidszone: Europe/Copenhagen
Logget ind som TorsdagBot#1234 (ID: ...)
Kanal fundet: #generelt (server: Min Server)
Planlagt afstemning: hver torsdag kl. 15:00 (Europe/Copenhagen)
Næste planlagte afstemning: Thursday 30-07-2026 kl. 15:00 CEST
```

### Brug `/testvote`

Skriv **`/testvote`** i Discord. Botten opretter **med det samme** præcis den samme afstemning i den valgte kanal.

- Kun brugeren med `OWNER_ID` i `.env` kan bruge kommandoen – alle andre får en privat afvisning.
- **Testafstemningen ændrer hverken datoen for den ugentlige afstemning eller beskedrotationen.** Torsdagens automatiske afstemning bliver altså stadig sendt som planlagt, med den besked der stod på tur.
- Som standard giver testafstemningen **ikke** en rigtig `@everyone`-notifikation (teksten er den samme). Vil du teste med ping, sæt `TEST_PING_EVERYONE=true` i `.env`.
- Vil du se en bestemt af de 16 torsdagsbeskeder, skriv fx **`/testvote besked:11`**. Uden tallet bruges den, der er næst i køen.

> Er `/testvote` ikke dukket op i Discord? Sæt `GUILD_ID` i `.env` og genstart botten – så registreres kommandoen med det samme. Ellers kan globale kommandoer tage op til en time. Tjek også at du inviterede botten med scope'et `applications.commands`.

### Test hele det automatiske forløb

Vil du se den automatiske afsendelse i praksis, så sæt fx dette i `.env`, genstart botten og vent et par minutter:

```
POLL_WEEKDAY=1      # 0=mandag, 1=tirsdag ... 3=torsdag
POLL_HOUR=14
POLL_MINUTE=35
```

Husk at slette (eller udkommentere) linjerne bagefter og at slette `poll_state.json`, hvis du vil køre testen flere gange samme dag.

---

## Trin 10 – Byg `.exe`-filen

1. Dobbeltklik på **`build.bat`** (eller kør den fra en kommandoprompt).
2. Scriptet installerer afhængighederne, installerer PyInstaller og bygger programmet.
3. Når det er færdigt, ligger filen her:

```
dist\TorsdagBot.exe
```

`build.bat` kopierer også `.env.example` og `start_bot.bat` over i `dist`-mappen.

4. **Åbn `dist`-mappen**, omdøb `.env.example` til `.env` og udfyld den (har du allerede en `.env` i projektmappen, kopieres den automatisk med).
5. Dobbeltklik på `TorsdagBot.exe` – eller på `start_bot.bat` i `dist`-mappen.

Mappen `dist` kan flyttes hen hvor du vil. Den skal bare indeholde:

```
dist\
 ├─ TorsdagBot.exe
 ├─ .env                 (dine indstillinger)
 ├─ poll_state.json      (oprettes automatisk)
 └─ torsdagbot.log       (oprettes automatisk)
```

**Teknisk:** Der bygges med `--onefile --console --collect-all tzdata`. `--collect-all tzdata` er nødvendig, fordi Windows ikke har en indbygget tidszone-database – uden den kan `Europe/Copenhagen` ikke slås op. Botten finder `.env` via `sys.executable` (altså `.exe`-filens placering), ikke via terminalens aktuelle mappe.

> 🛡️ Windows Defender eller SmartScreen kan advare om en nybygget `.exe`-fil, fordi den ikke er kodesigneret. Klik **Flere oplysninger → Kør alligevel**. Du kan også tilføje mappen som en undtagelse i din antivirus.

---

## Trin 11 – Start automatisk når Windows starter

### Metode A – Opgavestyring (anbefalet, virker også uden at nogen logger ind)

1. Tryk **Windows-tasten**, skriv **Opgavestyring** (Task Scheduler) og åbn den.
2. Klik **Opret opgave...** (Create Task) i højre side – *ikke* "Opret simpel opgave".
3. **Fanen Generelt:**
   - Navn: `TorsdagBot`
   - Vælg **Kør, uanset om brugeren er logget på eller ej** (hvis du vil have den til at køre uden login – kræver din Windows-adgangskode).
   - Sæt flueben i **Kør med de højeste rettigheder**, hvis programmet ellers ikke må starte.
   - Konfigurer til: din Windows-version.
4. **Fanen Udløsere (Triggers)** → **Ny...**:
   - Start opgaven: **Ved start** (At startup).
   - Sæt gerne flueben i **Udskyd opgaven i:** `1 minut` – så netværket er klar først.
   - Sæt eventuelt også en udløser: **Ved logon**.
5. **Fanen Handlinger (Actions)** → **Ny...**:
   - Handling: **Start et program**.
   - Program/script: `C:\Sti\til\dist\TorsdagBot.exe`
   - **Start i (valgfrit):** `C:\Sti\til\dist`  ← **udfyld dette felt!** (uden det kan Windows starte programmet fra `C:\Windows\System32`).
6. **Fanen Betingelser (Conditions):**
   - Fjern fluebenet i **Start kun opgaven, hvis computeren kører på vekselstrøm**, hvis det er en bærbar.
   - Sæt gerne flueben i **Start kun, hvis følgende netværksforbindelse er tilgængelig: Alle forbindelser**.
7. **Fanen Indstillinger (Settings):**
   - Sæt flueben i **Genstart opgaven, hvis den mislykkes** – fx hvert **5. minut**, op til **3 gange**.
   - Fjern fluebenet i **Stop opgaven, hvis den kører længere end...** – botten skal køre hele tiden.
8. Klik **OK** og indtast din adgangskode, hvis du bliver bedt om det.
9. Test det: højreklik på opgaven → **Kør**. Tjek at der kommer nye linjer i `torsdagbot.log`.

### Metode B – Startup-mappen (nemmest)

1. Tryk **Windows + R**, skriv `shell:startup` og tryk Enter.
2. Kopiér en **genvej** til `TorsdagBot.exe` (eller til `start_bot.bat`) ind i mappen, der åbner.
   - Højreklik på genvejen → **Egenskaber** → sæt **Start i:** til `dist`-mappens sti.
3. Botten starter nu, hver gang du logger ind på Windows.

---

## Trin 12 – Vigtigt: computeren skal være tændt

Botten er et helt almindeligt program – den kører kun, når din computer kører.

For at torsdagens afstemning bliver sendt, skal **alle tre** ting være opfyldt kl. 15:00 om torsdagen:

1. 🔌 **Computeren er tændt** – og er ikke i dvale eller slumretilstand.
2. 🌐 **Der er internetforbindelse.**
3. ▶️ **`TorsdagBot.exe` kører** (tjek i Jobliste / Task Manager).

Tips:
- Slå dvale fra i **Indstillinger → System → Strøm og batteri → Skærm og dvale** hvis maskinen skal stå tændt.
- Var computeren slukket kl. 15:00, sender botten afstemningen, så snart den starter – dog kun inden for `CATCH_UP_HOURS` timer (standard 6, altså indtil kl. 21:00). Derefter springes ugen over, så du ikke får en afstemning midt om natten.
- Skal afstemningen komme uanset om din computer kører, skal botten hostes et sted, der altid er tændt (fx en billig VPS eller en Raspberry Pi).

---

## Alle indstillinger

Alt sættes i `.env` (eller `config.json`, undtagen tokenet).

| Nøgle | Standard | Betydning |
|---|---|---|
| `DISCORD_TOKEN` | – | **Påkrævet.** Bottens token. Kun fra `.env`. |
| `CHANNEL_ID` | – | **Påkrævet.** Kanalen afstemningen sendes i. |
| `OWNER_ID` | – | Den eneste bruger der må køre `/testvote`. |
| `GUILD_ID` | tom | Server-ID. Gør `/testvote` synlig med det samme. |
| `POLL_WEEKDAY` | `3` | 0 = mandag … 3 = torsdag … 6 = søndag. |
| `POLL_HOUR` | `15` | Time (0–23). |
| `POLL_MINUTE` | `0` | Minut (0–59). |
| `TIMEZONE` | `Europe/Copenhagen` | Tidszone. |
| `POLL_MODE` | `auto` | `auto`, `native` (Discords poll) eller `buttons`. |
| `POLL_DURATION_HOURS` | `8` | Hvor længe en indbygget poll er åben (1–168). |
| `CATCH_UP_HOURS` | `6` | Hvor sent en "manglet" afstemning stadig må sendes. `0` slår det fra. |
| `CHECK_INTERVAL_SECONDS` | `20` | Hvor ofte uret tjekkes (5–300). |
| `PING_EVERYONE` | `true` | Skal den ugentlige afstemning pinge `@everyone`? |
| `TEST_PING_EVERYONE` | `false` | Skal `/testvote` pinge `@everyone`? |
| `EMOJI_CODE` | `<:code:887...>` | Server-emoji til "Efter 21:00 lol" (bygget ind, kan overstyres). |
| `EMOJI_CLUE` | `<:clue:104...>` | Server-emoji til "Efter 22:00 lol" (bygget ind, kan overstyres). |
| `EMOJI_CODEWEINER` | tom | Server-emoji til "Jeg kommer ikke". |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` eller `ERROR`. |

**Torsdagsbar** (i `config.json` under `"torsdagsbar"`, eller i `.env` med `TB_`-præfiks):

| Nøgle | Standard | Betydning |
|---|---|---|
| `server_id`, `voice_channel_ids`, `summary_channel_id` | – | **Påkrævet** for at slå torsdagsbaren til. |
| `min_minutes` | `5` | Mindste deltagelse for at tælle med. |
| `require_company` | `true` | Optjen kun tid, mens der er andre til stede. |
| `late_enabled` | `true` | Send "du er sent på den"-beskeder. |
| `late_channel_id` | tom | Kanal til forsinkelser (tom = opsummeringskanalen). |
| `late_grace_minutes` | `90` | Hvor sent en forsinkelsesbesked stadig må sendes. |
| `marathon_hours` | `5` | Grænse for 🏃 Marathonmand. |
| `speedrun_min_minutes` | `10` | Mindstevarighed for et gyldigt ⚡ Speedrun-besøg. |
| `big_words_hours` | `2` | Hvor sent man skal være for 🤥 Store ord. |
| `vote_sync_seconds` | `180` | Hvor ofte stemmer hentes fra Discords poll. |
| `admin_role_name` / `admin_role_id` | tom | Rolle med adgang til admin-kommandoerne. |
| `leaderboard_size` | `10` | Antal pr. side på leaderboardet. |
| `summary_show_records` | `true` | Vis rekorder/streaks i fredagsopsummeringen. |

### Torsdagsbeskederne

Botten skifter besked hver gang den sender den ugentlige afstemning, og starter forfra på listen efter den sidste. Med 16 beskeder går der altså **16 uger, før den samme tekst kommer igen**.

Rækkefølgen er:

| # | Besked |
|---|---|
| 1 | Det er torsdag! |
| 2 | Det er torsdag (Jens, det er dagen før fredag og dagen efter onsdag) |
| 3 | Torsdagsbaren åbner i dag, kommer du i baren? |
| 4 | Det er torsdag! Hvornår hopper du online i aften? |
| 5 | Torsdag er landet. Skal der games i aften? |
| 6 | Dagen før fredag kræver en vigtig beslutning: Hvornår kommer du online? |
| 7 | Torsdagsbaren åbner senere. Hvornår forventes dit fremmøde? |
| 8 | Endnu en torsdag, endnu en mulighed for at være social uden at forlade huset. |
| 9 | Kalenderen siger torsdag. Discord siger: Hvornår kommer folk online? |
| 10 | Torsdagsalarmen er gået! Meld din forventede ankomsttid. |
| 11 | Jens, bare så der ikke er nogen tvivl: Det er dagen efter onsdag og dagen før fredag. Hvornår kommer du online? |
| 12 | Breaking news: Det er torsdag. Flere oplysninger følger, når I har stemt. |
| 13 | Din ugentlige påmindelse om, at torsdag aften ikke planlægger sig selv. |
| 14 | Torsdagens vigtigste demokratiske handling begynder nu. Afgiv din stemme. |
| 15 | Serveren har brug for dig. Eller i det mindste brug for at vide, hvornår du kommer. |
| 16 | Torsdag.exe er startet. Vælg forventet login-tidspunkt. |

Alle beskederne får `@everyone` sat foran, og selve spørgsmålet i afstemningen er altid det samme korte **"Hvornår kommer du online i aften?"** – så den lange sjove tekst ikke står to gange i samme besked.

**Se hvor langt rotationen er nået:** botten skriver det i loggen, hver gang den starter:

```
Næste torsdagsbesked (7/16): Torsdagsbaren åbner senere. Hvornår forventes dit fremmøde?
```

**Ret i beskederne:** listen står i `bot.py` under `THURSDAY_MESSAGES`. Du kan tilføje, fjerne eller omskrive linjer – rækkefølgen i filen er også rækkefølgen de bruges i. Husk at bygge `.exe`-filen igen med `build.bat` bagefter.

**Forhåndsvis en bestemt besked:** `/testvote besked:11` sender afstemningen med besked nummer 11. Uden tallet bruges den, der står næst i køen. **En test rykker aldrig rotationen** – næste torsdag får præcis den besked, der stod på tur.

**Start rotationen forfra:** luk botten, sæt `"message_index": 0` i `poll_state.json` (eller slet filen), og start igen.

### Server-emojis

Ur-emojierne (🕖 🕗 🕣 🕘 🕙 ❌) er almindelige unicode-emojis og virker altid.

To af svarmulighederne har derudover jeres egne server-emojis **bygget ind som standard**, så du ikke behøver at gøre noget:

| Svarmulighed | Server-emoji |
|---|---|
| 🕘 Efter 21:00 lol | `:code:` (`<:code:887336573933334648>`) |
| 🕙 Efter 22:00 lol | `:clue:` (`<:clue:1044354323561320539>`) |

For at det virker, skal botten være **medlem af den server, emojierne hører til**. Kan en emoji ikke findes, skriver botten en advarsel i loggen og sender afstemningen **uden** den emoji – afstemningen fejler altså aldrig på grund af en emoji.

Emojierne vises som ikon på knappen (og på svarmuligheden i Discords indbyggede poll) samt i resultatlisten.

**Vil I bytte til andre emojis?** En bot kan ikke bruge formen `:clue:` – den skal have emojiens fulde ID:

1. Skriv `\:navn:` i en Discord-kanal – **med backslash foran** – og tryk Enter.
2. Discord skriver den fulde form, fx `<:clue:1044354323561320539>`.
3. Kopiér hele teksten (inklusive `<` og `>`) ind i `.env`. Nøglerne overstyrer standarderne:

```
EMOJI_CODE=<:code:887336573933334648>
EMOJI_CLUE=<:clue:1044354323561320539>
EMOJI_CODEWEINER=<:codeweiner:000000000000000000>
```

`EMOJI_CODEWEINER` sætter en emoji på "Jeg kommer ikke" – den er ikke sat som standard, men kan tilføjes her.

### To måder at stemme på

**Discords indbyggede poll** (standard, kræver discord.py 2.5+): Discord håndterer selv stemmer og resultater, så de aldrig kan gå tabt. Én stemme pr. person, som kan ændres, og resultatet vises direkte i Discord.

**Knapper** (bruges automatisk, hvis den indbyggede poll ikke kan bruges, eller ved `POLL_MODE=buttons`):

- Alle kan stemme, og hver person har præcis ét aktivt svar.
- Tryk på en anden knap for at skifte svar.
- Stemmetallene og en lille søjle vises i beskeden og opdateres med det samme.
- Hvert tryk giver en kort **privat (ephemeral)** bekræftelse, som kun du kan se.
- Stemmerne gemmes i `poll_state.json`, og knapperne virker stadig efter en genstart af botten (persistente Views).

---

## Torsdagsbar – voice-registrering og statistik

Denne del af botten registrerer automatisk, hvor længe hver person deltager i voicechat under torsdagsbaren, og laver statistik oven på det. Den er **helt valgfri**: udfylder du ikke indstillingerne nedenfor, kører afstemningen bare videre som før.

### Hvad den kan

- ⏱️ **Registrerer voice-tid** i udvalgte voicekanaler i tidsrummet **torsdag 19:00 → fredag 03:00** (dansk tid, sommer-/vintertid håndteres).
- 🍻 **Fredagsopsummering** kl. 12:00: hvem deltog og hvor længe, samlet tid, antal deltagere, aftenens højdepunkter (længst til stede, nye personlige rekorder, ny deltagerrekord, forlængede streaks). Sendes **kun én gang** pr. torsdagsbar – også ved genstart.
- 📊 **Statistik, streaks, rekorder, leaderboard og live-status** via `/torsdagsbar`-kommandoerne.
- 💾 **Gemmes permanent i en SQLite-database** (`torsdagsbar.db` ved siden af `.exe`-filen), så intet forsvinder ved genstart. SQLite er en del af Python – ingen ekstra installation.
- 🔁 **Robust**: håndterer genstart midt i en aften, kanalskift, tabt internet, at man allerede sad der kl. 19:00, og at man stadig sidder der kl. 03:00. Botter registreres ikke.

### Sådan slår du den til

Alt sættes i **`config.json`** (under `"torsdagsbar"`) eller i **`.env`** (med `TB_`-præfiks). Du skal bruge tre ID'er – kopiér dem med **Developer Mode** slået til (se [Trin 6](#trin-6--slå-developer-mode-til)):

1. **Server-ID** – højreklik på serverikonet → Kopiér server-ID.
2. **Voicekanal-ID(er)** – højreklik på selve voicekanalen → **Kopiér kanal-ID**. Flere kanaler adskilles med komma.
3. **Tekstkanal-ID** til fredagsopsummeringen.

Enten i `config.json`:

```json
"torsdagsbar": {
  "server_id": 123456789012345678,
  "voice_channel_ids": [111111111111111111, 222222222222222222],
  "summary_channel_id": 333333333333333333,
  "min_minutes": 5,
  "require_company": true,
  "admin_role_name": "Torsdagsbar-admin"
}
```

…eller i `.env`:

```
TB_SERVER_ID=123456789012345678
TB_VOICE_CHANNEL_IDS=111111111111111111,222222222222222222
TB_SUMMARY_CHANNEL_ID=333333333333333333
TB_MIN_MINUTES=5
TB_ADMIN_ROLE_NAME=Torsdagsbar-admin
```

Når det er sat rigtigt, skriver botten ved opstart:

```
Torsdagsbar aktiveret · server: ... · voicekanaler: ... · opsummering: ... · min. deltagelse: 5 min
Torsdagsbar: /torsdagsbar-kommandoer registreret.
Torsdagsbar: næste registrering starter torsdag ... kl. 19:00 CEST
```

### Ekstra rettigheder

Botten skal ud over afstemnings-rettighederne kunne **se og læse** de valgte voicekanaler (**Vis kanal** / **View Channel** — den behøver ikke selv at kunne tale) og kunne **sende beskeder + indlejre links** i opsummeringskanalen. Ingen privilegerede intents skal slås til: `voice_states` er en del af standard-intents, så voice-registrering virker uden ændringer i Developer Portal.

### Kommandoer

Alle svar vises i pæne embeds. `bruger`, `periode` og `år` kan udelades.

**For alle:**

| Kommando | Hvad den gør |
|---|---|
| `/torsdagsbar profil [bruger] [periode] [år]` | **Ét samlet kort:** tid, torsdagsbarer, streak, typisk ankomsttid, holdt-hvad-du-lovede, titler, badges og antal citater. |
| `/torsdagsbar stats [bruger] [periode] [år]` | Statistik: samlet tid, antal torsdagsbarer, gennemsnit, længste enkeltdeltagelse, streak, placering + top 10. |
| `/torsdagsbar streak [bruger]` | Nuværende og længste streak + top 10 aktive streaks. |
| `/torsdagsbar rekorder [periode] [år]` | Flest deltagere, længste individuelle deltagelse, længste aften, længste streaks, flest torsdagsbarer/timer. |
| `/torsdagsbar leaderboard [sortering] [periode] [år]` | Rangliste med blader-knapper. Sortér efter tid, antal, gennemsnit, streak, længste streak eller længste enkeltdeltagelse. |
| `/torsdagsbar live` | Hvem der sidder i baren lige nu, hvor længe, samlet tid, og hvor længe der er tilbage. |
| `/quote add bruger:@X tekst:"..."` | Gem et citat på en bruger. |
| `/quote random` | Vis et tilfældigt citat fra hele citat-bogen. |
| `/quote delete id:` | Slet et citat (dit eget, eller som admin). |
| `/quotes [bruger]` | Alle citater gemt på en bruger, nyeste først. |

**Perioder:** `i_år` (**standard**), `sidste_år`, `sidste_uge`, `denne_måned`, `sidste_3_måneder`, `sidste_6_måneder`, `hele_perioden`. Parameteren `år:2025` slår et bestemt kalenderår op og overtrumfer `periode`.

Eksempler:

```
/torsdagsbar profil
/torsdagsbar stats bruger:@Christian periode:sidste_3_måneder
/torsdagsbar leaderboard sortering:streak år:2025
/quote add bruger:@Christian tekst:"Slog alle de andre ihjel med kniv"
/quotes bruger:@Christian
```

### 📅 Årsbaseret statistik

Statistikken er opdelt pr. kalenderår, og **standardvisningen er indeværende år**. Ved nytår starter leaderboard og statistik altså naturligt forfra på 0 — men **intet slettes**: gamle år hentes frem igen med `periode:sidste_år` eller `år:2024`, og `periode:hele_perioden` viser alt fra begyndelsen.

**Streaks løber videre hen over nytår**, da en streak handler om torsdage i træk — ikke om kalenderåret.

**Kun for administratorer** (kræver **Administrer server** eller den valgte rolle):

| Kommando | Hvad den gør |
|---|---|
| `/torsdagsbar status` | Registreringens og databasens status + hvornår næste opsummering sendes. |
| `/torsdagsbar opsummering dato:ÅÅÅÅ-MM-DD [gensend]` | Forhåndsvis (kun dig) eller gensend en opsummering for en tidligere torsdagsbar. |
| `/torsdagsbar korriger bruger dato handling minutter` | Tilføj tid, sæt samlet tid, eller nulstil rettelser for en bruger (hvis botten var offline eller registrerede forkert). |
| `/torsdagsbar aflys dato:ÅÅÅÅ-MM-DD [fortryd]` | Markér en torsdag som aflyst/ikke-statistikgivende – bryder ikke streaks. `fortryd:True` ophæver aflysningen. |
| `/torsdagsbar genberegn` | Genberegner al statistik, streaks og rekorder ud fra de gemte sessioner. |

### 🍻 Fredagsopsummeringen og aftenens titler

Hver fredag kl. 12:00 sender botten en opsummering af torsdagens bar: hvem der deltog og hvor længe, samlet tid og antal deltagere — plus **aftenens titler**. En kategori vises **kun, hvis nogen opfylder den**; ellers udelades den helt.

| Titel | Hvem får den |
|---|---|
| 👑 **Aftenens konge** | Længst online i alt den aften. Ved præcis lige tid deles titlen. |
| 🏃 **Marathonmand** | Alle med **mere end 5 timer** samme aften. |
| 🐦 **Early Bird** | Først online. |
| 🦉 **Lukkede baren** | Sidst online — seneste registrerede sluttidspunkt. |
| 🎯 **Holdt hvad du lovede** | Kom online inden for det tidsrum, de stemte på. |
| 🎭 **Surprise!** | Stemte "Jeg kommer ikke", men dukkede alligevel op. |
| ⚡ **Speedrun** | Aftenens korteste gyldige besøg — mindst **10 minutter**, så korte forbindelsesfejl ikke tæller. |
| 🤥 **Store ord** | Stemte på et bestemt tidsrum, men kom mindst **2 timer** efter dets slutning. |
| 🐌 **Slow starter** | Aftenens største forsinkelse i forhold til det lovede tidsrum. |

"Efter 21:00", "Efter 22:00" og "Jeg kommer ikke" har ikke et præcist sluttidspunkt og tæller derfor **ikke** med i 🤥 og 🐌.

Grænserne kan justeres med `marathon_hours`, `speedrun_min_minutes` og `big_words_hours`.

### ⏰ "Du er sent på den"

Botten holder øje med, om folk kommer inden for det tidsrum, de stemte på. Er man ikke dukket op, når ens tidsrum slutter, får man en (kærlig) opsang med tag:

> Hva' jeg synes @Christian er sent på den!

Der er **10 forskellige tekster**, så det ikke bliver det samme hver gang, og der sendes **højst én besked pr. person pr. aften**.

**Undtagelser:** stemte man **"Efter 21:00"**, **"Efter 22:00"** eller **"Jeg kommer ikke"**, får man aldrig en forsinkelsesbesked — de to første er åbne løfter, og den sidste lovede jo ikke at komme (de fanges i stedet af 🎭 Surprise!).

Beskeden sendes i opsummeringskanalen, medmindre `late_channel_id` peger et andet sted hen. Kommer botten først op længe efter deadline, sendes der intet (`late_grace_minutes`, standard 90) — så en sen genstart ikke spammer med timegamle forsinkelser. Slås fra med `late_enabled: false`.

### 💬 Citat-bogen

Gem de bedste udtalelser fra serveren:

```
/quote add bruger:@Christian tekst:"Slog alle de andre ihjel med kniv"
/quote random
/quotes bruger:@Christian
/quote delete id:42
```

For hvert citat gemmes **hvem det tilhører**, **selve citatet**, **hvem der tilføjede det** og **datoen**. Alle må tilføje citater; et citat kan kun slettes af den, der tilføjede det — eller af en admin.

### 🪪 Profilkortet

`/torsdagsbar profil [bruger]` samler alt ét sted: ⏱️ samlet tid · 🍻 antal torsdagsbarer · 🔥 nuværende og længste streak · 🕒 typisk ankomsttid · 📊 placering · 🎯 hvor ofte man holder hvad man lover (fx "14/18 torsdage, 78 %") · 🏅 optjente titler · 🎖️ badges · 💬 antal citater.

**Badges** tildeles automatisk ud fra data — der er ikke noget at vedligeholde:

🍻 Stamgæst (10/25/50/100 torsdagsbarer) · 🔥 Streak-mester (streak ≥ 5) · 👑 Kongelig · 🏃 Marathonløber · ⚡ Speedrunner · 🦉 Natteravn · 🐦 Morgenfugl · 🎯 Pålidelig (≥ 80 % holdte løfter) · 🎭 Uforudsigelig.

### Hvor stemmerne kommer fra

De stemmeafhængige funktioner (🎯, 🤥, 🐌, 🎭 og "du er sent på den") kræver, at botten ved, **hvad hver person stemte**. Bruger I Discords indbyggede poll, ligger stemmerne hos Discord, så botten henter dem automatisk hvert par minutter og gemmer dem i databasen. Bruger I knapper, gemmes de med det samme. **I skal ikke gøre noget** — det virker i begge tilstande.

> ⚠️ **Bemærk:** stemmerne gemmes først fra den torsdag, hvor denne opdatering kører. Tidligere torsdage har ingen gemt stemmedata, så 🎯 / 🤥 / 🐌 / 🎭 og "Holdt hvad du lovede"-procenten tæller **fra nu af**. 👑 / 🏃 / 🐦 / 🦉 / ⚡ virker derimod **bagud i hele historikken**, da de kun bruger voice-data.

### Sådan virker registreringen og databasen

- Når en rigtig bruger tilslutter sig en registreret voicekanal **inden for vinduet**, åbnes en *session*. Når de går, lukkes den, og varigheden gemmes. Kommer de tilbage, lægges tiderne sammen.
- **Man optjener kun tid, mens der er selskab** — altså kun i de øjeblikke, hvor mindst én **anden** rigtig bruger også er i baren samtidig. Sidder man helt alene, tælles den tid ikke (så man ikke bare kan joine og "farme" point). Reglen kan slås fra med `require_company: false`. Fordi tiden altid **genberegnes ud fra sessionerne**, gælder reglen også **bagud i historikken** — gammel solo-tid falder automatisk væk, uden nogen migrering.
- **Skift mellem to registrerede kanaler** tæller ikke som at forlade baren. (Bemærk: "selskab" måles på tværs af alle de registrerede voicekanaler — er I i hver jeres kanal, tæller det stadig som selskab.)
- Sad man der allerede **kl. 19:00**, tælles fra 19:00. Sidder man der stadig **kl. 03:00**, afsluttes automatisk kl. 03:00.
- Ved **genstart** genoptages åbne sessioner for dem, der stadig sidder i kanalerne; sessioner for dem, der er gået, lukkes ved bottens sidste livstegn – så en hel aften går ikke tabt.
- Alle tidspunkter gemmes som **UTC** i databasen og vises som **dansk lokal tid** i Discord. Bruger-ID er den permanente identifikation (navne kan ændres og gemmes ved siden af).
- **Streaks** tælles ud fra tællende torsdagsbarer i træk, hvor man deltog mindst `min_minutes`. **Aflyste** torsdage tæller neutralt og bryder ikke en streak. Alt kan genberegnes ud fra sessionerne.
- Databasen (`torsdagsbar.db`) oprettes automatisk ved siden af `.exe`-filen og har indekser, så statistik og leaderboard forbliver hurtige selv efter års historik.

### Test af torsdagsbaren uden at vente til torsdag

- Sæt midlertidigt tidsrummet, så det passer med nu – fx i `config.json` under `"torsdagsbar"`: `"start_hour"`, `"end_hour"` (og evt. `"weekday"` til dagens ugedag). Genstart botten, gå ind i en registreret voicekanal, og kør `/torsdagsbar live`.
- Kør `/torsdagsbar opsummering dato:ÅÅÅÅ-MM-DD gensend:True` for at teste opsummeringen på en valgt dato.
- De medfølgende automatiske tests dækker registrering, kanalskift, genstart, opsummering, streaks, rekorder, live og aflysning:

```bat
python tests\test_torsdagsbar.py
```

---

## Fejlfinding

| Problem | Løsning |
|---|---|
| `KONFIGURATIONSFEJL: DISCORD_TOKEN mangler` | `.env`-filen ligger ikke ved siden af `.exe`-filen, hedder `.env.txt`, eller tokenet er ikke udfyldt. |
| `Login mislykkedes: DISCORD_TOKEN er ugyldigt` | Tokenet er forkert eller nulstillet. Hent et nyt under **Bot → Reset Token**. |
| `KANALFEJL: Kanalen med ID ... findes ikke` | Forkert `CHANNEL_ID`, eller botten er ikke medlem af serveren. Kopiér ID'et igen med Developer Mode. |
| `MANGLENDE RETTIGHEDER i #kanal` | Giv bottens rolle `Vis kanal`, `Send beskeder` og `Indlejre links` – både på serveren og i kanalens egne tilladelser. |
| `@everyone` giver ingen notifikation | Botten mangler `Nævn @everyone` (Mention Everyone). Tjek også kanalens egne tilladelser. |
| `/testvote` findes ikke i Discord | Sæt `GUILD_ID` i `.env` og genstart. Botten skal være inviteret med scope'et `applications.commands`. |
| `Kun bottens ejer må bruge denne kommando` | `OWNER_ID` i `.env` passer ikke med dit bruger-ID. |
| `Tidszonen 'Europe/Copenhagen' kunne ikke findes` | Kør `python -m pip install tzdata`. I en `.exe` skal der bygges med `--collect-all tzdata` (det gør `build.bat`). |
| Afstemningen kom to gange | Du har to kopier af botten kørende. Tjek Jobliste for flere `TorsdagBot.exe`. |
| Afstemningen kom slet ikke | Læs `torsdagbot.log`. Var computeren tændt kl. 15:00? Kørte programmet? Var der internet? |
| Vil du "nulstille" en torsdag | Luk botten, slet `poll_state.json` (eller ret `last_poll_date`), og start igen. |
| Samme besked to torsdage i træk | Er `poll_state.json` slettet eller flyttet, starter rotationen forfra. Filen skal ligge ved siden af `.exe`-filen. |
| `:clue:` vises som tekst i stedet for et ikon | Brug den fulde form `<:clue:123...>` i `.env` – se [Server-emojis](#server-emojis). |
| `Server-emojien ... blev ikke fundet` i loggen | Emoji-ID'et er forkert, eller botten er ikke medlem af den server, emojien hører til. |
| Konsolvinduet lukker med det samme | Start via `start_bot.bat`, eller åbn en kommandoprompt i mappen og skriv `TorsdagBot.exe`, så kan du læse fejlbeskeden. |
| Windows Defender blokerer `.exe`-filen | Filen er ikke kodesigneret. Vælg **Flere oplysninger → Kør alligevel**, eller tilføj mappen som undtagelse. |
| `/torsdagsbar` findes ikke i Discord | Torsdagsbaren er ikke slået til (`server_id`/`voice_channel_ids`/`summary_channel_id` mangler), eller kommandoerne er ikke synkroniseret endnu. Sæt `GUILD_ID` og genstart. |
| Ingen voice-tid registreres | Er voicekanalens ID rigtigt (højreklik på selve **voicekanalen**)? Kan botten se kanalen (View Channel)? Er klokken inden for torsdag 19:00–fredag 03:00? |
| Fredagsopsummeringen kom ikke | Var botten tændt fredag kl. 12:00 (inden for 6 timer)? Tjek at `summary_channel_id` er en tekstkanal, botten må skrive i. Ellers: `/torsdagsbar opsummering dato:... gensend:True`. |
| En bruger fik forkert tid (bot var offline) | Ret med `/torsdagsbar korriger`. Var hele torsdagen aflyst: `/torsdagsbar aflys`. |
| Vil nulstille torsdagsbar-statistikken | Luk botten og slet `torsdagsbar.db` (ved siden af `.exe`-filen). Den oprettes tom igen ved næste start. |
| 🎯/🤥/🐌/🎭 vises aldrig | De kræver gemte stemmer. De tæller først fra den torsdag, opdateringen kørte — og botten skal have været tændt, da afstemningen blev sendt. |
| Ingen forsinkelsesbeskeder | Er `late_enabled` slået fra? Har folk stemt "Efter 21:00/22:00" eller "kommer ikke" (de får aldrig besked)? Startede botten mere end 90 min efter deadline? |
| Leaderboardet ser tomt ud i januar | Standardperioden er **i år**, som lige er startet forfra. Brug `periode:sidste_år` eller `periode:hele_perioden`. |
| `/quote` eller `/profil` mangler | Kommandoerne registreres kun, når torsdagsbaren er slået til. Sæt `GUILD_ID` og genstart, og tryk Ctrl+R i Discord. |

Loggen i `torsdagbot.log` (ved siden af `.exe`-filen) indeholder alt: login, oprettede afstemninger, afgivne stemmer, manglende rettigheder og forbindelsesproblemer. Start altid fejlfindingen der.

---

## Licens

Fri afbenyttelse. God fornøjelse – vi ses torsdag! 🍻
