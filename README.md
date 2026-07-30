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

De tre nederste svarmuligheder kan få jeres egne server-emojis (`:clue:`, `:code:`, `:codeweiner:`) sat på – se [Server-emojis](#server-emojis).

Botten er skrevet i Python med [discord.py](https://discordpy.readthedocs.io/) og kan pakkes til en enkelt `TorsdagBot.exe`, der kan køre på en almindelig Windows-computer.

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
18. [Fejlfinding](#fejlfinding)

---

## Hvad kan botten?

- ✅ Sender afstemningen **automatisk hver torsdag kl. 15:00** i tidszonen `Europe/Copenhagen` (sommer-/vintertid håndteres automatisk).
- ✅ **Skifter besked hver torsdag** – 16 forskellige tekster på rotation, så det ikke bliver den samme sætning hver uge.
- ✅ Sender **kun én afstemning pr. torsdag** – også hvis du genstarter programmet 10 gange. Datoen gemmes i `poll_state.json`.
- ✅ Virker uanset om programmet startes **før**, **under** eller **efter** kl. 15:00 om torsdagen.
- ✅ Bruger **Discords indbyggede poll-funktion** (discord.py 2.5+). Kan ikke den bruges, skifter botten automatisk til **knapper med persistente Views**.
- ✅ Knapper: alle kan stemme, hver person har **ét aktivt svar**, man kan **skifte svar**, **stemmetallene vises i beskeden**, stemmerne **gemmes lokalt** og **knapperne virker stadig efter en genstart**.
- ✅ Ejerbeskyttet testkommando **`/testvote`**.
- ✅ Tydelig logning i konsollen og i `torsdagbot.log`.
- ✅ **Automatisk genforbindelse** hvis internettet eller Discord falder ud.
- ✅ Tokenet står **aldrig** i kildekoden – kun i `.env`.

---

## Filer i projektet

| Fil | Hvad den gør |
|---|---|
| `bot.py` | Hele botten |
| `requirements.txt` | Python-pakker der skal installeres |
| `.env.example` | Skabelon til dine indstillinger – **kopiér den til `.env`** |
| `config.example.json` | Valgfrit alternativ til `.env` (undtagen tokenet) |
| `build.bat` | Bygger `dist\TorsdagBot.exe` |
| `start_bot.bat` | Starter botten (og genstarter den hvis den lukker) |
| `README.md` | Denne vejledning |

Filer der **oprettes automatisk**, når botten kører:

| Fil | Hvad den indeholder |
|---|---|
| `poll_state.json` | Datoen for den seneste afstemning, hvor langt beskedrotationen er nået, + de afgivne stemmer |
| `torsdagbot.log` | Log over hvad botten har lavet |

> 📁 **Vigtigt:** `.env`, `config.json`, `poll_state.json` og `torsdagbot.log` skal ligge i **samme mappe som `TorsdagBot.exe`** – ikke i den mappe, du tilfældigvis står i, når du starter programmet. Botten finder selv filerne ud fra placeringen af `.exe`-filen.

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
| `EMOJI_CLUE` | tom | Server-emoji til "Efter 21:00 lol". |
| `EMOJI_CODE` | tom | Server-emoji til "Efter 22:00 lol". |
| `EMOJI_CODEWEINER` | tom | Server-emoji til "Jeg kommer ikke". |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` eller `ERROR`. |

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

Jeres **egne server-emojis** kan ikke skrives som `:clue:` af en bot – Discord oversætter kun `:navn:` for rigtige brugere. Botten skal have emojiens fulde ID:

1. Skriv `\:clue:` i en Discord-kanal – **med backslash foran** – og tryk Enter.
2. Discord skriver den fulde form, fx `<:clue:112233445566778899>`.
3. Kopiér hele teksten (inklusive `<` og `>`) ind i `.env`:

```
EMOJI_CLUE=<:clue:112233445566778899>
EMOJI_CODE=<:code:112233445566778900>
EMOJI_CODEWEINER=<:codeweiner:112233445566778901>
```

Botten skal være medlem af den server, emojien kommer fra. Kan en emoji ikke findes – eller er den skrevet forkert – skriver botten en advarsel i loggen og sender afstemningen **uden** den emoji. Afstemningen fejler altså aldrig på grund af en emoji.

Emojierne vises som ikon på knappen (og på svarmuligheden i Discords indbyggede poll) samt i resultatlisten.

### To måder at stemme på

**Discords indbyggede poll** (standard, kræver discord.py 2.5+): Discord håndterer selv stemmer og resultater, så de aldrig kan gå tabt. Én stemme pr. person, som kan ændres, og resultatet vises direkte i Discord.

**Knapper** (bruges automatisk, hvis den indbyggede poll ikke kan bruges, eller ved `POLL_MODE=buttons`):

- Alle kan stemme, og hver person har præcis ét aktivt svar.
- Tryk på en anden knap for at skifte svar.
- Stemmetallene og en lille søjle vises i beskeden og opdateres med det samme.
- Hvert tryk giver en kort **privat (ephemeral)** bekræftelse, som kun du kan se.
- Stemmerne gemmes i `poll_state.json`, og knapperne virker stadig efter en genstart af botten (persistente Views).

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

Loggen i `torsdagbot.log` (ved siden af `.exe`-filen) indeholder alt: login, oprettede afstemninger, afgivne stemmer, manglende rettigheder og forbindelsesproblemer. Start altid fejlfindingen der.

---

## Licens

Fri afbenyttelse. God fornøjelse – vi ses torsdag! 🍻
