# Krausenkamera — överlämning

## Vad som ska byggas

En kamera monterad i locket på en Brewtools F80-jäsare, som tittar rakt ned genom ett siktglas mot ölytan. Den ska:

1. Ta en bildruta per minut under hela jäsningen och arkivera den på NAS.
2. Mäta krausenhöjden i millimeter med lasertriangulering och publicera den via MQTT.
3. Erbjuda en live-vy i Home Assistant vid behov.

Syftet är att kvalificera nya jäststammar: hur högt och hur snabbt de bygger skum, och om skummet är torrt och sprickigt eller vått och klättrande. Det avgör risken för blow-off upp i utrustning som inte ska ha skum i sig, och gör det möjligt att köra en okänd jäst på lågt starttryck med mätning som beslutsunderlag i stället för defensivt högt tryck som dämpar jästuttrycket.

Detta är ett kvalificeringsinstrument, inte en permanent processgivare. Det körs ett par satser per ny stam och monteras sedan av.

## Hårdvara

| Del | Detalj |
|---|---|
| Dator | Raspberry Pi 3B+, Debian 13 Trixie, 1 GB RAM |
| Kamera | Raspberry Pi Camera Module 3 **NoIR**, standard 75° (IMX708) |
| Belysning | IR-lysdiod 850 nm ingjuten i en PMMA-stav, separat port |
| Laser | Röd 650 nm modul med drivkort, logikingång "S" |
| Switchning | MOSFET-drivkort, 3,3 V-kompatibla, ett per last |
| Nätverk | WiFi |

Pi:n och all optik sitter i en styv kropp ovanpå siktglaset. **Ingenting går in i röret** — det är bara det som klipper synfältet.

## Optisk geometri

- Siktglas i DN40-port i locket, innerdiameter 38 mm
- Avstånd lins till rörmynning (kallas **L**): cirka 40–45 mm, ska mätas upp
- Från rörmynning till maximal vätskenivå: 104 mm
- Rörmynningen begränsar synfältet, inte objektivet — kameran ser 41° vertikalt, röret ger cirka 46°
- Synlig cirkel på vörtytan blir därmed cirka 126–137 mm

Rörmynningen syns som en ring i bilden. Den är fast referens för bildregistrering. Att ringen beskärs i topp och botten är avsiktligt — sensorn är 16:9 och man vinner yta i sidled.

**Lasern sitter 15,5 mm från kameraaxeln, parallell med den.** Punktens radiella läge i bilden ger avståndet till ytan. Känsligheten är cirka 1 px/mm vid vilonivå och 6 px/mm när krausen närmar sig mynningen, i binnat läge. Centroidberäkning ger sub-pixel, alltså kring 0,3–0,5 mm upplösning.

## Mjukvarukrav

**picamera2**, inte legacy-stacken. Installeras med `apt`, inte pip — bindningarna kommer från libcamera. På Debian 13 gäller PEP 668, så en venv behöver `--system-site-packages` för att se picamera2.

**Fast fokus.** `AfMode` manuell, `LensPosition` i dioptrier (1 delat med avståndet i meter). För 140 mm blir det 7,1. Exakt värde tas fram genom att svepa och välja skarpast — linskalibreringen varierar mellan exemplar. Sveptet ska göras **med arbetsbelysningen tänd**, eftersom fokusplanet för 850 nm skiljer sig från synligt ljus.

**Låst exponering.** `AeEnable=False` med explicit `ExposureTime` och `AnalogueGain`. `AwbEnable=False` med fasta `ColourGains`. Utan detta kompenserar automatiken bort exakt den ljusstyrkeförändring som ska mätas när krausen bygger, och tidsserien blir värdelös för automatisk analys.

**En enda videokonfiguration hela tiden**, 2304×1296 (sensorns 2×2-binnade läge). Bildrutor greppas ur strömmen i stället för att växla till stillbildsläge — lägesbyten kräver omkonfigurering av sensorn och är det enda som faktiskt är långsamt. Binningen ger dessutom fyra gånger signalen per pixel.

**Två bildrutor per mätcykel:**
- **A** — belysning på, laser av. Ger krausenstruktur och relief.
- **B** — belysning av, laser på. Laserpunkten är då det enda ljusa i en nästan svart bild, vilket gör centroidberäkningen trivial.

**Exponeringstid är gratis.** Ingenting rör sig — krausen stiger millimeter per minut. 50–100 ms är helt oproblematiskt och är den första ratten att vrida på om ljuset inte räcker.

## Arkitektur

Pi:n äger hela mätcykeln: tänd, exponera, växla, exponera, släck, beräkna, publicera, spara.

Bilder skrivs till en monterad SMB-share på NAS. Lokal fallback-katalog om mounten är nere, men **gallra den när mounten kommer tillbaka** — obegränsad buffring på SD-kort dödar dem.

MJPEG-ström för live-vy, tillagd i HASS som `camera: platform: mjpeg`. HASS ligger inte i datavägen för mätdata.

Krausenhöjd ut via MQTT, loggas bredvid densitet, temperatur och tryck.

## Arbetsordning

1. `rpicam-hello --list-cameras` ska visa imx708. Gör den inte det är det kabeln, inte mjukvaran.
2. `rpicam-still -o test.jpg --autofocus-mode manual --lens-position 7.1` — skarp bild innan någon Python skrivs.
3. Svep LensPosition mot ett testmål på arbetsavståndet, lås bästa värdet.
4. Lås exponering och vitbalans till fasta värden.
5. Videokonfiguration med grepp ur strömmen, två bildrutor med GPIO-växling emellan.
6. SMB-mount och sparande.
7. MJPEG-ström till HASS.
8. Centroidberäkning och MQTT — sist.

## Att veta om miljön

Pi 3B+ har 1 GB RAM och **orkar inte köra VS Code Remote-SSH-servern**. Utveckling sker mot en Samba-delning från en annan maskin, körning via SSH i terminal.

Kamerabuffertar allokeras ur CMA. I binnat läge är de cirka 4,5 MB och det räcker, men vid full upplösning kan taket nås — höj då `cma` i `/boot/firmware/config.txt`.

## Kalibrering

Trianguleringen ska **inte** räknas analytiskt. Objektivet har distorsion, ingångspupillens exakta läge är okänt och laserns monteringsvinkel har fel. Kalibrera i stället punktens pixelläge mot kända vattennivåer och interpolera i en tabell. Det tar bort alla tre felkällorna på en gång.

Enheten monteras av och på mellan satser. Vid varje fyllning står vätskan på känd nivå — läs av laserpunkten då och jämför mot kalibreringen. Avviker den har något flyttat sig. Bygg in den kontrollen i uppstartsrutinen från början.
