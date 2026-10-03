# DS18B20, 1-Wire på GPIO24

```
dtoverlay=w1-gpio,gpiopin=24        i /boot/firmware/config.txt
VDD 3.3 V (stift 17)  ·  DQ GPIO24 (stift 18)  ·  GND (stift 20)
4.7 kΩ mellan DQ och 3.3 V
läs ur /sys/bus/w1/devices/28-*/temperature, tusendels grader
```

⚠️ **3,3 V, aldrig 5.** DS18B20 klarar båda, men matad med 5 V drar den
datalinjen till 5 V och Pi:ns GPIO tål 3,3. En pullup till 5 V genom 4,7 kΩ
begränsar strömmen till 0,30 mA genom klämdioden och överlevs — det hände här
2026-09-11 och GPIO18 klarade sig — men det är tur, inte konstruktion.

Sedan 2026-10-03 sitter en Pimoroni Wide Input SHIM på stift 1–12, där både
lampan (GPIO17) och bussen (GPIO18) satt. Allt flyttades till klustret stift
17–20: 3,3 V, GPIO24 (bussen), GPIO10 (lampan) och GND. Lasern på GPIO27 är
borta. Före flytten: GPIO17 lampan, GPIO27 lasern, GPIO18 bussen.

## Offset mellan givarna, mätt 2026-09-12

Alla tre buntade ihop, tio minuter, tills ingen rört sig mer än 0,05 °C på två
minuter. De sista sex avläsningarna:

| id | avläst | offset | placering |
|---|---|---|---|
| `28-ef39cb356461` | 23.3120 °C | referens | TC-stosen till kamerahuset |
| `28-f161ca356461` | 23.1870 °C | −0.1250 | experimentkortet på locket |
| `28-fe3ecb356461` | 23.2500 °C | −0.0620 | ambient utanför lådan |
| `28-713ecb356461` | — | ej uppmätt | **aluminiumplattan i hus v2**, i fickan bredvid modulen (2026-10-03) |

> Plattgivaren kom till med hus v2 och har ingen uppmätt offset mot de andra.
> Den ska bli tjänstens `--lid-sensor` när inkörningen visat att den följer
> kameran minst lika bra som hylsgivaren, och temperaturkoefficienten ska då
> mätas om mot den.

**Största skillnad 0,125 °C**, alltså två kvantiseringssteg — vid 0,63 mm/°C
är det 0,08 mm om två givare jämförs rakt av.

Absolut noggrannhet är ±0,5 °C och spelar ingen roll: vi mäter förändringar.
Offseten spelar roll bara när två givare jämförs med varandra, till exempel
locket mot luften i lådan, och då ska talen ovan dras bort först.

> Placeringen ovan är den planerade. **Id:na är slumpmässiga och går inte att
> härleda ur en position** — flyttas en givare utan att den här tabellen
> uppdateras finns inget sätt att upptäcka det i efterhand.

## Varför TC-stosen

Den är svetsad i 8-tumslocket och kamerahuset kläms fast i den, så den *är*
skarven mellan den stora rostfria massan och ABS-huset. Metall ger dessutom god
kontakt och snabbt svar.

Men den ligger på locksidan om plasten, och ABS leder dåligt — stosen är därför
en **ledande indikator** på modulens temperatur, inte ett mått på den. Samma
förhållande som `SensorTemperature` har fast från andra hållet, så tillsammans
klämmer de in optiken mellan sig.

Tejpa fast och lägg en bit skum över. En givare mot metall med luft på baksidan
läser någonstans mellan metallen och luften.
