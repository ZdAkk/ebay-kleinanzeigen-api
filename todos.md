# TODO: Structured filter support in /inserate

## Goal

Extend `/inserate` (GET) so that category-level filters (year, brand, fuel, mileage,
transmission, car type, etc.) can be passed as typed query parameters — without the
caller having to know Kleinanzeigen's internal URL syntax.

The `/inserate-by-url` endpoint (POST) already covers this via URL passthrough.
This task is about offering the same power through a clean, structured API.

---

## What needs to change

### 1. `routers/inserate_ultra.py` — new query params

```
category_slug   str   "s-autos", "s-wohnwagen-mobile"
category_id     int   216, 220
year_from       int   2008
year_to         int   2024  (None = open-ended)
brands          str   comma-separated: "volkswagen,audi"
fuel            str   comma-separated: "lpg,cng"
transmission    str   "automatik", "manuell"
car_type        str   comma-separated: "kombi,suv"
mileage_from    int   km lower bound  (unit TBD — see note below)
mileage_to      int   km upper bound
art             str   article type, e.g. "wohnwagen"
```

### 2. `scrapers/inserate_ultra_optimized.py` — URL builder

Add a `build_filter_url(params)` helper that constructs the Kleinanzeigen filter URL
from structured params. This is the reverse of `utils/parse_kleinanzeigen_url.py`.

Example output:
```
https://www.kleinanzeigen.de/s-autos/volkswagen/klima/
  k0c216
  +autos.ez_i:2008,
  +autos.fuel_s:(lpg,cng)
  +autos.marke_s:volkswagen
  +autos.shift_s:automatik
  +autos.typ_s:(kombi,suv)
```

---

## Open questions — need more URL examples

The following are not yet fully understood:

| Filter        | URL key        | Known values          | Open question                          |
|---------------|----------------|-----------------------|----------------------------------------|
| Mileage       | `autos.km_i`   | `2,` seen in examples | What is the unit? Is `2` = 2 * 10 000? |
| Car type      | `autos.typ_s`  | `kombi`, `suv`        | Full value list?                       |
| Fuel          | `autos.fuel_s` | `lpg`, `cng`          | All accepted values?                   |
| Condition     | ?              | ?                     | New / used filter URL format?          |
| Category prefix | varies       | `autos.*`, `wohnwagen_mobile.*` | How to look up per category? |

**Action**: collect more real Kleinanzeigen search URLs from different categories
(motorcycles, real estate, electronics) to identify the full filter key namespace
before implementing the URL builder.

---

## Implementation order

1. [ ] Collect more URL examples per category (blocker for URL builder)
2. [ ] Implement `build_filter_url()` in `utils/` (reverse of parser)
3. [ ] Add new params to `routers/inserate_ultra.py`
4. [ ] Wire params into `scrapers/inserate_ultra_optimized.py`
5. [ ] Add unit tests for the URL builder
6. [ ] Update `/convert-url` to also validate whether all parsed params
       can now be expressed via `/inserate` (shrink the `unmapped` set)
