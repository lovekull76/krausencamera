# Krausencamera

Kameraövervakning av krausen (jästskummet) på jäskärlet. Del av Gammabrewery.

## Hårdvara

- **Raspberry Pi 3B+** Rev 1.3 — `krausencamera`
- **Camera Module 3 NoIR** (imx708_noir), 4608×2592, 10-bit RGGB
  - Modes: 1536×864 @120fps · 2304×1296 @56fps · 4608×2592 @14fps
  - NoIR = IR-belysning möjlig utan att störa jäsningen med synligt ljus
- 905 MB RAM + zram-swap (~905 MB) · 28 GB SD (11 % använt)
- **WiFi only**, ingen kabel — via garage-APen

## Åtkomst

Alla kommandon i detta repo utgår från SSH-aliaset `krausencamera`. Lägg det i
`~/.ssh/config` så fungerar de oförändrat oavsett vilken IP din Pi har:

```
Host krausencamera
    HostName <din-pi-ip>
    User pi
    IdentityFile ~/.ssh/id_ed25519
```

> Adresser, MAC och övriga enheter på det egna nätet ligger i `LOCAL.md`,
> som är gitignorerad. Den filen är platsspecifik och hör inte hemma i repot.

**Passwordless sudo** behövs för att installera paket och systemd-tjänster
icke-interaktivt. Raspberry Pi OS brukar leverera det, men filen kan saknas:

```bash
sudo sh -c 'echo "pi ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/010_pi-nopasswd \
  && chmod 440 /etc/sudoers.d/010_pi-nopasswd && visudo -c'
sudo -n true && echo FUNKAR
```

`visudo -c` är inte valfritt: en trasig sudoers-fil låser ute dig från root helt,
och då är det SD-kortet i en annan dator som gäller.

## Mjukvara på Pi:n

- Debian 13 **Trixie**, **64-bit** (aarch64), Python **3.13.5**
- `rpicam-apps-lite` + libcamera 0.7.2 — `rpicam-still` / `rpicam-vid` / `rpicam-hello`
- `python3-picamera2` **0.3.37**, numpy 2.2.4, `python3-gpiozero` 2.0.1 (installerade)

```bash
sudo apt update && sudo apt install -y python3-picamera2
```

> Python 3.13 + Trixie: picamera2 ska installeras som **apt-paket**, inte via pip —
> bindningarna kommer från libcamera. PEP 668 gäller, så ett venv måste skapas med
> `--system-site-packages` för att se dem. `python3-gpiozero` fanns redan i imagen.
> Installationen drar in Qt/PyQt5 som beroende (~500 MB); det är förhandsvisnings-
> stacken och behövs inte för headless drift, men går inte att välja bort.

## ✅ Strömförsörjning: löst

**Lösning: MeanWell 5,1 V / 15 W direkt på GPIO-stiften.** Ingen micro-USB.

Slutverifiering 2026-09-02 22:53, boot med `throttled=0x0`:

```
Tomgång 40s                 underspänning:  0/20
1 kärna, 20s                underspänning:  0/10   arm=1400MHz  49.4'C
2 kärnor, 20s               underspänning:  0/10   arm=1399MHz  55.8'C
3 kärnor, 20s               underspänning:  0/10   arm=1200MHz  60.1'C
4 kärnor, 30s               underspänning:  0/15   arm=1200MHz  65.5'C
Kamera ensam 2304x1296 60s  underspänning:  0/30   arm=600MHz   48.3'C
Kamera + 2 kärnor, 60s      underspänning:  0/30   arm=1200MHz  60.1'C
4 kärnor + kamera, 60s      underspänning:  0/30   arm=1200MHz  68.8'C
```

Slutläge `0x80000` — enbart bit 19 (*soft temp limit har inträffat*).
**Ingen underspänningsbit satt över huvud taget**, och 0 voltage-rader i `dmesg`.

### Vad felet faktiskt var

| Uppsättning | Tomgång | Under last |
|---|---|---|
| Originalkabel + trafo | **95,6 %** underspänning, 600 MHz | — |
| Ny kabel + samma trafo | 0 % | underspänning, 53 s-episod |
| Labbagg via dålig micro-USB-stump, 1 A gräns | ~10 % | — |
| Labbagg på GPIO-stift, **1 A gräns** | 0 % | **död vid 4 kärnor** |
| Labbagg på GPIO-stift, 5,1 A gräns | 0 % | underspänning vid 4 kärnor |
| **MeanWell 5,1 V/15 W på stift** | **0 %** | **rent hela vägen** |

Tre oberoende felkällor, alla i strömvägen — aldrig i nätdelens märkeffekt:

1. **Originalkabeln, ~1,5 Ω.** Beräknat ur 0,45 V fall vid 0,3 A. Dominerande fel.
2. **Bänkaggregatets 1 A-gräns** (default på extraslotten). Pi 3B+ drar ~300 mA i
   medel men har WiFi-transienter på 1,5–2 A. Vid 1 A gick den i CC-läge.
3. **Bänkledningarna, ~0,39 Ω.** Syntes först när gränsen höjts till 5,1 A.

**Diagnostiskt tips:** resistivt fall *varnar först* (`Undervoltage detected`,
nedklockning, återhämtning). En strömgräns kollapsar rakt genom brownout **utan
ett ord i loggen**. Tyst död under last ⇒ misstänk strömgräns, inte kabel.

### Termik: kylfläns monterad 2026-09-02 23:19

Standard RPi-fläns. Samma ramp, samma MeanWell-matning, direkt jämförbar:

| Steg | Utan fläns | Med fläns |
|---|---|---|
| 1 kärna | 49,4 °C · 1400 MHz · 0/10 | 46,2 °C · 1400 MHz · 0/10 |
| 2 kärnor | 55,8 °C · 1399 MHz · 0/10 | 52,6 °C · 1400 MHz · 0/10 |
| 3 kärnor | 60,1 °C · 1200 MHz · **4/10** | 58,5 °C · **1399 MHz** · **0/10** |
| 4 kärnor | 65,5 °C · 1200 MHz · 14/15 | 62,8 °C · 1199 MHz · 12/15 |
| Kamera ensam | 48,3 °C · 0/30 | 49,4 °C · 0/30 |
| **Kamera + 2 kärnor** | 60,1 °C · 1200 MHz · **7/30** | 59,1 °C · **1399 MHz** · **1/30** |
| 4 kärnor + kamera | 68,8 °C · 1200 MHz · 30/30 | 67,1 °C · 1199 MHz · 29/30 |

**Resultat:** den realistiska arbetslasten (kamera + 2 kärnor) går nu på full
klocka i praktiken hela tiden — 1/30 mot 7/30, och lägsta klocka 1399 mot
1200 MHz. Tre kärnor blev helt throttlingfritt.

**Men vinsten är bara 2–3 °C och konstant över alla laststeg.** Det betyder att
den dominerande värmemotståndet inte är chip→fläns utan **fläns→luft**. Vid
4 kärnor är den fortfarande limitad 12/15 — flänsen mättar utan luftrörelse.

⚠️ Konsekvens för kapslingen: 3 °C marginal äts upp av en tät kropp. **En större
fläns inuti lådan löser det inte** — det är samma mättade fläns→luft-motstånd.
Det som ger verklig effekt är en **ledningsväg ut ur kapslingen**: termisk pad
från SoC/fläns mot kroppens vägg, helst mot siktglaset eller en metalldel med
kontakt utåt.

**Billigaste lösningen är dock mjukvara:** briefingen säger att livevyn behövs
"vid behov". Starta MJPEG-strömmen **på begäran** från HASS i stället för att
låta den gå konstant. Det är systemets enda ihållande last — tas den bort
ligger driftfallet på kameran ensam, 49,4 °C, utan att röra temp-gränsen.

### Bittolkning (referens)

| Värde | Bitar | Betydelse |
|---|---|---|
| `0x0` | — | friskt |
| `0x50005` | 0, 2, 16, 18 | underspänning *nu* + throttlad *nu* + har inträffat |
| `0xd0008` | 3, 16, 18, 19 | soft temp limit *nu*, spänning har inträffat |
| `0x80000` | 19 | endast temp-limit har inträffat — spänningen har varit ren |

Sticky-bitarna nollställs bara av reboot. Låg hex-siffra udda ⟺ bit 0 satt.

## Köra livevyn

```bash
rsync -avz --exclude '.git' ./src/ krausencamera:~/krausencamera/
ssh krausencamera 'cd ~/krausencamera && setsid nohup python3 liveview.py </dev/null >liveview.log 2>&1 &'
```

Öppna sedan **http://krausencamera:8080/** i valfri webbläsare
(eller Pi:ns IP direkt om värdnamnet inte resolvar på ditt nät).
`--auto` låser upp exponering/vitbalans för inriktning — **aldrig vid mätning**.

Två fällor som kostade tid, värda att komma ihåg:

- `pkill -f liveview` matchar **sin egen ssh-kommandorad** och dödar sitt eget
  skal. Kör kill och start som två separata `ssh`-anrop.
- `ssh host 'cmd &'` hänger tills kanalen stängs. `setsid nohup … </dev/null`
  och separata anrop är det som fungerar pålitligt.

Status 2026-09-03: livevyn verifierad, 30 fps på lores. Referensräkningen testad
med två överlappande tittare — lampan förblev tänd tills den sista gick.
GPIO17 drivs på riktigt via gpiozero 2.0.1 (`python3-gpiozero` fanns redan).

## Arbetsflöde

Utveckla lokalt i denna mapp → deploya med `rsync` över SSH → kör som systemd-tjänst på Pi:n.
Ingen sshfs/Samba-mount: segt och bräckligt över WiFi.

```bash
rsync -avz --delete --exclude '.git' ./src/ krausencamera:~/krausencamera/
```

## Arkitektur (fastställd 2026-09-02)

Avviker från briefingen på en punkt: **ingen MJPEG-kamera i HASS.**

| Kanal | Innehåll | Konsument |
|---|---|---|
| **MQTT** (discovery) | krausenhöjd i mm, mätvärden att logga | HASS |
| **Webbvy på Pi:n** | live-bild, ansluts med telefon/webbläsare | människa, vid behov |
| **NAS (SMB)** | en bildruta/minut, arkiv | efteranalys |

HASS ligger inte i bildvägen alls — bara datavägen.

### IR-lampan tänds när någon ansluter

Konsekvenser att bygga in från början:

1. **Två konsumenter av lampan.** Mätcykeln behöver den tänd (bildruta A) *och*
   släckt (bildruta B, där laserpunkten ska vara det enda ljusa i en nästan
   svart bild). En ansluten tittare som håller lampan tänd **förstör bildruta B**.
   Mätcykeln måste vinna: livevyn tappar en bildruta i sekunden det tar.
2. **Referensräkning med timeout.** Lampan på om ≥1 tittare. En webbläsarflik som
   dör utan att stänga snyggt lämnar annars lampan tänd i all evighet — krävs
   heartbeat eller inaktivitetstimeout, inte bara "anslutning öppen".
3. **⚠️ LED:ens termiska drift.** Ljusutbytet sjunker när kapseln blir varm. En
   tittare som tittar i tio minuter lämnar lampan het, och nästa bildruta A blir
   då mörkare än en tagen från kallt läge. Det är **exakt den ljusstyrkeändring
   briefingen vill mäta** när krausen bygger. Låst exponering hjälper inte —
   felet sitter i ljuskällan, inte i kameran.
   Åtgärd: ta alltid bildruta A efter en **fast tändtid från känt läge**, och
   logga lampans föregående tillstånd så analysen kan flagga påverkade rutor.

### Termik: löst av arkitekturen

Utan ihållande MJPEG-ström är driftfallet "kamera ensam" = **49,4 °C, ingen
throttling**, tio grader under gränsen. Webbvyn är sporadisk. Kapslingen har
därmed rejäl marginal att äta av.
- [ ] DHCP-reservation på `.177` i UniFi — klienten syns i UniFi men
      integrations-APIet avslöjar inte om IP:n är reserverad. Sätts i UI:t.
