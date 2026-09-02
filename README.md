# Krausencamera

Kamera som mäter **krausenhöjd** — jästskummets höjd — i en jäsare, för att
kvalificera nya jäststammar. Hur högt och hur snabbt bygger stammen skum, och
är skummet torrt och sprickigt eller vått och klättrande?

Det avgör risken för blow-off upp i utrustning som inte ska ha skum i sig, och
gör det möjligt att köra en okänd jäst på lågt starttryck med mätning som
beslutsunderlag, i stället för defensivt högt tryck som dämpar jästuttrycket.

Ett kvalificeringsinstrument, inte en permanent processgivare: det körs ett par
satser per ny stam och monteras sedan av. Del av Gammabrewery.

## Princip

En Raspberry Pi med **Camera Module 3 NoIR** sitter i en styv kropp ovanpå ett
siktglas i jäsarens lock och tittar rakt ned mot ölytan. Ingenting går in i
röret. Två bildrutor per mätcykel:

| Ruta | Belysning | Laser | Ger |
|---|---|---|---|
| **A** | på | av | krausenstruktur och relief |
| **B** | av | på | laserpunkt i nästan svart bild → trivial centroid |

En röd laser 15,5 mm från kameraaxeln, parallell med den, ger avstånd till ytan
genom **triangulering**: punktens radiella läge i bilden översätts till höjd.
850 nm IR-belysning gör att jäsningen inte störs av synligt ljus.

Trianguleringen räknas medvetet **inte** analytiskt — objektivet har distorsion,
ingångspupillens läge är okänt och laserns monteringsvinkel har fel. I stället
kalibreras punktens pixelläge mot kända vätskenivåer och interpoleras i en tabell,
vilket tar bort alla tre felkällorna på en gång.

## Arkitektur

| Kanal | Innehåll | Konsument |
|---|---|---|
| MQTT (discovery) | krausenhöjd i mm | Home Assistant |
| Webbvy på Pi:n | live-bild i webbläsare | människa, vid behov |
| NAS (SMB) | en bildruta/minut | efteranalys |

Home Assistant ligger inte i bildvägen — bara datavägen.

## ⚠️ Läs detta först: strömförsörjning

En Raspberry Pi 3B+ trippar underspänning vid ~4,63 V och blir då **nedklockad
från 1400 till 600 MHz**. I den här uppsättningen orsakades det av tre oberoende
fel i strömvägen — inget av dem i nätdelens märkeffekt:

1. En micro-USB-kabel med **~1,5 Ω** resistans. Ensam stod den för 95,6 % tid i
   underspänning vid tomgång.
2. Ett bänkaggregat med strömgränsen på **1 A**. Pi 3B+ drar ~300 mA i medel men
   har WiFi-transienter på 1,5–2 A.
3. Bänkledningar med **~0,39 Ω**.

**Lösning: MeanWell 5,1 V / 15 W direkt på GPIO-stiften**, förbi micro-USB-kontakten
och ingångspolyfusen. Efter det: noll underspänning under samtliga laster.

Kontrollera alltid innan du bygger något ovanpå:

```bash
vcgencmd get_throttled     # ska vara 0x0
vcgencmd measure_clock arm # ska vara 1400000000
dmesg | grep -ci voltage   # ska vara 0
```

**Diagnostiskt tips:** resistivt spänningsfall *varnar först* i loggen
(`Undervoltage detected`, nedklockning, återhämtning). En strömgräns kollapsar
rakt genom brownout **utan ett ord**. Tyst död under last ⇒ misstänk strömgräns,
inte kabel.

## Hårdvara

| Del | Detalj |
|---|---|
| Dator | Raspberry Pi 3B+, Debian 13 Trixie 64-bit, 1 GB RAM |
| Kamera | Camera Module 3 **NoIR**, 75°, IMX708 |
| Belysning | IR-lysdiod 850 nm ingjuten i PMMA-stav, separat port |
| Laser | Röd 650 nm modul med drivkort, logikingång |
| Switchning | MOSFET-drivkort, 3,3 V-kompatibla, ett per last |
| Ström | MeanWell 5,1 V / 15 W på GPIO-stift 2/4 + 6 |
| Kylning | Standard RPi-kylfläns (se termiknoteringen i CLAUDE.md) |

## Snabbstart

```bash
sudo apt update && sudo apt install -y python3-picamera2
rsync -avz --exclude '.git' ./src/ krausencamera:~/krausencamera/
ssh krausencamera 'cd ~/krausencamera && \
  setsid nohup python3 liveview.py </dev/null >liveview.log 2>&1 &'
```

Öppna **http://krausencamera:8080/**. IR-belysningen tänds när första tittaren
ansluter och släcks när den sista försvinner.

Kör `--auto` för att låsa upp exponering och vitbalans vid inriktning av huset.
**Aldrig vid mätning** — automatiken kompenserar då bort exakt den
ljusstyrkeförändring som ska mätas när krausen bygger.

## Status

Fungerar: livevy, 30 fps, referensräknad IR-styrning.
Återstår: fokuskalibrering i IR, mätcykel, centroidberäkning, MQTT, NAS-arkivering.

Se [`CLAUDE.md`](CLAUDE.md) för mätdata och detaljer, och
[`krausenkamera_briefing.md`](krausenkamera_briefing.md) för optisk geometri
och kalibreringsmetod.
