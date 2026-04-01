# StudyVault - minimalni izvedljivi projekt (MVP)

## Namen

Ta dokument opisuje, kako bi lahko aplikacija **StudyVault** izgledala kot **minimalni izvedljivi projekt**, ki je se vedno dovolj dober za predmetne tehnicne zahteve.

Cilj MVP ni izdelati vseh moznih funkcionalnosti, ampak pokazati:

- delujoc frontend in backend
- mikrostoritveno zasnovo
- `docker compose` postavitev
- 1 relacijsko in 1 nerelacijsko bazo
- `API gateway` oziroma proxy
- centralizirano logiranje
- `CI/CD` pipeline
- uporabo `Cloudflare`
- uporabo `S3 API` prek `MinIO`

---

## 1. Najmanjsi smiseln uporabniski scenarij

MVP naj podpira eno jasno zgodbo:

1. uporabnik se prijavi
2. nalozi datoteko
3. vidi seznam svojih datotek
4. poisce datoteko po imenu ali oznaki
5. vidi zadnje aktivnosti

To je dovolj, da projekt pokaze celotno pot od uporabniskega vmesnika do mikrostoritev, baz, objektne shrambe in logiranja.

---

## 2. Minimalne funkcionalnosti

Obvezne funkcionalnosti MVP:

- prijava uporabnika prek `Keycloak`
- upload datoteke
- prikaz seznama datotek
- osnovno iskanje po metapodatkih
- belezenje aktivnosti

Funkcionalnosti, ki jih je smiselno pustiti za kasneje:

- deljenje datotek med uporabniki
- obvestila
- napredno filtriranje
- predogled dokumentov
- napredne administrativne funkcionalnosti nad osnovnim admin panelom
- masovni reindex

---

## 3. Minimalni nabor API klicev

Za MVP zadosca najmanj **4 zunanje API klice**, ki jih lahko tudi jasno pokazete na predstavitvi.

| Endpoint | Metoda | Namen |
|---|---|---|
| `/api/files` | `POST` | upload datoteke v sistem |
| `/api/catalog/files` | `GET` | vrne seznam uporabnikovih datotek |
| `/api/search?q=...` | `GET` | poisce datoteke po metapodatkih |
| `/api/activity/me` | `GET` | vrne zadnje aktivnosti trenutnega uporabnika |

Priporocen dodatni peti klic:

| Endpoint | Metoda | Namen |
|---|---|---|
| `/api/files/{fileId}/download` | `GET` | prenos datoteke iz `MinIO` |

---

## 4. Predlagane mikrostoritve za MVP

Da projekt ostane izvedljiv, zadostujejo naslednje storitve:

### 4.1 Frontend

- `React`
- prikaz prijave, seznama datotek, upload obrazca, iskanja in aktivnosti

### 4.2 API gateway / reverse proxy

- `Nginx`
- enotna vstopna tocka za frontend in vse `API` poti

### 4.3 Auth

- `Keycloak`
- prijava, uporabniki, vloge, `OIDC/JWT`

### 4.4 File Service

- sprejme upload
- datoteko shrani v `MinIO`
- objavi osnovni dogodek o uploadu

### 4.5 Catalog Service

- hrani metapodatke datotek v `PostgreSQL`
- vrne seznam datotek
- vrne osnovne podrobnosti datoteke

### 4.6 Search Service

- hrani iskalni pogled v `MongoDB`
- izvaja osnovno iskanje po imenu, oznakah ali tipu

### 4.7 Activity Service

- belezi dogodke v `MongoDB`
- vraca zgodovino aktivnosti uporabnika

---

## 5. Podatkovne shrambe

### Relacijska baza

- `PostgreSQL`
- uporablja jo `Catalog Service`
- hrani: `file_id`, `owner_id`, `filename`, `mime_type`, `size`, `created_at`, `tags`

### Nerelacijska baza

- `MongoDB`
- uporabljata jo `Search Service` in `Activity Service`
- hrani iskalne dokumente in activity zapise

### Objektna shramba

- `MinIO`
- uporablja `S3 API`
- hrani dejanske binarne datoteke

---

## 6. Minimalni potek sistema

### 6.1 Prijava

1. uporabnik odpre frontend
2. frontend preusmeri uporabnika na `Keycloak`
3. po prijavi frontend dobi `JWT/OIDC` token
4. vse naslednje zahteve gredo prek `Nginx`

### 6.2 Upload datoteke

1. frontend poklice `POST /api/files`
2. `Nginx` zahtevo preusmeri na `File Service`
3. `File Service` shrani binarno vsebino v `MinIO`
4. `Catalog Service` shrani metapodatke v `PostgreSQL`
5. `Activity Service` ustvari activity zapis v `MongoDB`
6. `Search Service` ustvari iskalni dokument v `MongoDB`

### 6.3 Seznam datotek

1. frontend poklice `GET /api/catalog/files`
2. `Catalog Service` prebere metapodatke iz `PostgreSQL`
3. rezultat se vrne uporabniku

### 6.4 Iskanje

1. frontend poklice `GET /api/search?q=zapiske`
2. `Search Service` isce v `MongoDB`
3. rezultat se vrne v frontend

### 6.5 Aktivnosti

1. frontend poklice `GET /api/activity/me`
2. `Activity Service` prebere zapise iz `MongoDB`
3. rezultat se prikaze na dashboardu

---

## 7. Docker Compose postavitev

Minimalni `docker-compose` naj vsebuje:

- `frontend`
- `nginx`
- `keycloak`
- `file-service`
- `catalog-service`
- `search-service`
- `activity-service`
- `postgres`
- `mongodb`
- `minio`
- `elasticsearch`
- `logstash`
- `kibana`

To je dovolj, da je arhitektura dejansko mikrostoritvena in da pokrije vse predmetne zahteve.

---

## 8. Centralizirano logiranje

Za zahtevo po centraliziranem logiranju zadostuje:

- vse storitve pisajo strukturirane `JSON` loge
- `Logstash` pobere loge iz vsebnikov
- `Elasticsearch` jih shrani
- `Kibana` omogoca pregled logov

Na predstavitvi je dovolj pokazati:

- log upload zahtevka
- log iskanja
- log napake ali `401/403` odziva

---

## 9. CI/CD minimum

Minimalni `CI/CD` v `GitHub Actions` lahko vsebuje:

1. checkout repozitorija
2. build frontenda
3. osnovne avtomatizirane teste backend storitev
4. build `Docker` slik
5. po zelji push slik v registry

Za MVP zadosca, da projekt vsebuje:

- nekaj osnovnih unit testov backend logike
- teste glavnih `API` klicev
- vsaj en preprost smoke oziroma end-to-end scenarij za glavni uporabniski tok

Ze tak pipeline zadostuje, da pokazete avtomatiziran razvojni tok.

---

## 10. Cloudflare minimum

`Cloudflare` lahko v MVP uporabi samo naslednje funkcije:

- `DNS`
- `TLS`
- osnovna zascita pred prometom

To je dovolj, da izpolnite zahtevo po `Cloudflare account`, brez dodatnih kompleksnih nastavitev.

---

## 11. Kako MVP pokrije vse zahteve predmeta

| Zahteva | Kako jo izpolni MVP |
|---|---|
| Projekt na Git repozitoriju | celoten projekt je v `GitHub` repozitoriju |
| frontend + backend | `React` frontend in `FastAPI` backend storitve |
| mikrostoritve + `docker compose` | vsaka komponenta tece v svojem vsebniku |
| 1 relacijska in 1 nerelacijska baza | `PostgreSQL` + `MongoDB` |
| `API gateway` oziroma proxy | `Nginx` |
| centralizirano logiranje | `ELK` |
| `CI/CD pipeline` | `GitHub Actions` |
| `Cloudflare` account | domena gre cez `Cloudflare` |
| uporaba `S3 API` | `File Service` uporablja `MinIO` |

---

## 12. Kaj pokazati na predstavitvi

Na predstavitvi je dovolj pokazati naslednji tok:

1. prijava prek `Keycloak`
2. upload datoteke v sistem
3. prikaz seznama uporabnikovih datotek
4. iskanje datoteke po imenu ali oznaki
5. prikaz zadnjih aktivnosti uporabnika
6. vpogled v log zapise v `Kibana`

Po zelji lahko pokazete se:

- prenos datoteke prek `download` endpointa
- kratek pregled `docker compose` postavitve
- osnovni pregled `CI/CD` pipeline izvedbe

Na zagovoru ali demonstraciji je dovolj pokazati naslednji tok:

1. prijava uporabnika
2. upload ene datoteke
3. prikaz datoteke v seznamu
4. iskanje te datoteke
5. prikaz aktivnosti
6. vpogled v loge v `Kibana`
7. kratek pogled v `docker compose` storitve
8. kratek pogled v `GitHub Actions` pipeline

To je dovolj mocan in hkrati dovolj majhen MVP, da je realno izvedljiv v okviru studentskega projekta.
