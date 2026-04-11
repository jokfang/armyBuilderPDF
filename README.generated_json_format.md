# Format du JSON généré

Ce document décrit la structure du JSON produit par :

- [`build_army_books_from_urls.py`](./build_army_books_from_urls.py)
- [`extract_army_web.py`](./extract_army_web.py)

Le format est pensé pour être consommé ensuite par :

- [`generate_army_pdf.py`](./generate_army_pdf.py)
- [`generate_army_pdfs_from_dir.py`](./generate_army_pdfs_from_dir.py)

## Vue d'ensemble

Chaque fichier JSON représente un army book complet.

Il contient :

- des métadonnées globales sur la faction et le système de jeu
- les sections de règles et de sorts
- la liste des unités

## Structure racine

Le document racine est un objet JSON avec cette forme générale :

```json
{
  "sourcePdf": "https://army-forge.onepagerules.com/army-info/age-of-fantasy/BOOK_UID",
  "sourceUrl": "https://army-forge.onepagerules.com/army-info/age-of-fantasy/BOOK_UID",
  "sourceBookUid": "BOOK_UID",
  "systemCode": "AOF",
  "systemName": "Age of Fantasy",
  "armyName": "Beastmen",
  "version": "3.5.2",
  "introduction": "Short faction introduction...",
  "backgroundStory": "Longer faction background...",
  "armyWideSpecialRule": [],
  "specialRules": [],
  "auraSpecialRules": [],
  "armySpells": [],
  "units": []
}
```

## Champs racine

### `sourcePdf`

Type : `string`

URL source de l'army book. Dans la pratique, cette valeur contient la même URL que `sourceUrl`.

### `sourceUrl`

Type : `string`

URL `army-info` utilisée comme source.

Exemple :

```text
https://army-forge.onepagerules.com/army-info/age-of-fantasy/TciwNI3AOMXAM-dr?armyName=Beastmen
```

### `sourceBookUid`

Type : `string`

Identifiant unique de l'army book dans Army Forge.

### `systemCode`

Type : `string`

Code court du système.

Exemples courants :

- `GF`
- `GFF`
- `AOF`
- `AOFS`
- `AOFR`

### `systemName`

Type : `string`

Nom complet du système de jeu.

Exemples :

- `Grimdark Future`
- `Grimdark Future: Firefight`
- `Age of Fantasy`

### `armyName`

Type : `string`

Nom de la faction ou de l'army book.

### `version`

Type : `string`

Version textuelle de l'army book.

Exemple :

```text
3.5.2
```

### `introduction`

Type : `string`

Texte d'introduction court de la faction.

Peut contenir des retours à la ligne.

### `backgroundStory`

Type : `string`

Texte de background plus long.

Peut contenir des retours à la ligne.

### `armyWideSpecialRule`

Type : `array<object>`

Liste des règles spéciales considérées comme "army-wide".

### `specialRules`

Type : `array<object>`

Liste des règles spéciales non-aura.

### `auraSpecialRules`

Type : `array<object>`

Liste des règles spéciales contenant `Aura` dans leur nom source.

### `armySpells`

Type : `array<object>`

Liste des sorts de l'armée.

### `units`

Type : `array<object>`

Liste complète des unités.

## Format d'une règle

Les éléments de `armyWideSpecialRule`, `specialRules` et `auraSpecialRules` partagent la même structure de base.

Forme typique :

```json
{
  "name": "Bestial",
  "description": "Rule description...",
  "keywords": ["Bestial"]
}
```

### Champs

#### `name`

Type : `string`

Nom affiché de la règle.

Si une traduction est appliquée, c'est généralement le nom traduit.

#### `description`

Type : `string`

Description textuelle de la règle.

Remarque importante :

- ce champ peut être absent après application des traductions
- le générateur PDF sait reconstituer la description à partir de `keywords`

#### `keywords`

Type : `array<string>`

Liste de mots-clés permettant de retrouver la règle source dans le dictionnaire de traduction.

Dans la pratique, c'est souvent une liste à un seul élément contenant le nom source en anglais.

## Format d'un sort

Les éléments de `armySpells` ont cette forme :

```json
{
  "name": "Surge of Power",
  "cost": 1,
  "description": "Spell description...",
  "keywords": ["Surge of Power"]
}
```

### Champs

#### `name`

Type : `string`

Nom du sort.

#### `cost`

Type : `number`

Coût ou seuil du sort.

#### `description`

Type : `string`

Description du sort.

Comme pour les règles, ce champ peut être absent si la description est reconstruite à partir du dictionnaire de traduction.

#### `keywords`

Type : `array<string>`

Mot-clé source utilisé pour retrouver le sort dans le dictionnaire.

## Format d'une unité

Chaque entrée de `units` a une structure proche de :

```json
{
  "name": "Kemba Brute Boss",
  "size": 1,
  "cost": 135,
  "page": 0,
  "uniqueHero": false,
  "quality": "3+",
  "defense": "3+",
  "tough": "6",
  "specialRules": ["Bestial", "Hero", "Tough(6)"],
  "weapons": [],
  "upgrades": [],
  "unitType": "Heroes"
}
```

### Champs

#### `name`

Type : `string`

Nom de l'unité.

#### `size`

Type : `number`

Taille de l'unité.

#### `cost`

Type : `number`

Coût de base de l'unité.

#### `page`

Type : `number`

Champ réservé au pipeline de rendu.

Dans les JSON générés depuis Army Forge, la valeur initiale est `0`.

#### `uniqueHero`

Type : `boolean`

Vaut `true` quand l'unité possède à la fois les règles `Hero` et `Unique` dans les données source.

#### `quality`

Type : `string`

Valeur de qualité formatée avec `+`.

Exemple :

```text
3+
```

#### `defense`

Type : `string`

Valeur de défense formatée avec `+`.

Exemple :

```text
4+
```

#### `tough`

Type : `string`

Valeur extraite de la règle `Tough(...)`.

Exemple :

```text
6
```

Si l'unité n'est pas coriace, la chaîne peut être vide.

#### `specialRules`

Type : `array<string>`

Liste des règles spéciales appliquées à l'unité sous forme de libellés déjà formatés.

Exemples :

- `Bestial`
- `Hero`
- `Tough(6)`
- `Impact(1)`

#### `weapons`

Type : `array<object>`

Liste des armes de l'unité.

#### `upgrades`

Type : `array<object>`

Liste des groupes d'amélioration.

#### `unitType`

Type : `string`

Champ optionnel.

Présent seulement si Army Forge fournit un type d'unité.

## Format d'une arme

Chaque entrée de `weapons` a cette forme :

```json
{
  "name": "Heavy Hand Weapon",
  "range": "-",
  "attacks": "A6",
  "ap": "2",
  "special": "-"
}
```

### Champs

#### `name`

Type : `string`

Nom de l'arme.

#### `range`

Type : `string`

Portée affichée.

Exemples :

- `-`
- `12"`
- `24"`

#### `attacks`

Type : `string`

Nombre d'attaques, préfixé par `A`.

Exemple :

```text
A6
```

#### `ap`

Type : `string`

Valeur d'AP extraite des règles spéciales de l'arme.

Exemples :

- `-`
- `1`
- `2`

#### `special`

Type : `string`

Texte des règles spéciales de l'arme, hors AP.

Exemples :

- `-`
- `Shred`
- `Deadly(3), Poison`

## Format d'un groupe d'amélioration

Chaque entrée de `upgrades` a cette forme :

```json
{
  "type": "Replace Heavy Hand Weapon",
  "options": []
}
```

### Champs

#### `type`

Type : `string`

Libellé du groupe d'amélioration.

Exemples :

- `Replace Heavy Hand Weapon`
- `Upgrade with one`
- `Upgrade with any`

#### `options`

Type : `array<object>`

Liste des options de ce groupe.

## Format d'une option d'amélioration

Chaque entrée de `options` a cette forme :

```json
{
  "name": "Flameforged Great Weapon",
  "details": "A6, Shred",
  "cost": "+10pts"
}
```

### Champs

#### `name`

Type : `string`

Nom court de l'option.

#### `details`

Type : `string`

Détails affichés de l'option.

Selon le type de gain, cela peut être :

- un profil d'arme condensé
- une règle spéciale
- un libellé brut

#### `cost`

Type : `string`

Coût formaté.

Exemples :

- `Free`
- `+5pts`
- `+20pts`

## Exemple complet simplifié

```json
{
  "sourcePdf": "https://army-forge.onepagerules.com/army-info/age-of-fantasy/TciwNI3AOMXAM-dr?armyName=Beastmen",
  "sourceUrl": "https://army-forge.onepagerules.com/army-info/age-of-fantasy/TciwNI3AOMXAM-dr?armyName=Beastmen",
  "sourceBookUid": "TciwNI3AOMXAM-dr",
  "systemCode": "AOF",
  "systemName": "Age of Fantasy",
  "armyName": "Beastmen",
  "version": "3.5.2",
  "introduction": "Short intro...",
  "backgroundStory": "Long background...",
  "armyWideSpecialRule": [
    {
      "name": "Bestial",
      "keywords": ["Bestial"]
    }
  ],
  "specialRules": [
    {
      "name": "Unique",
      "keywords": ["Unique"]
    }
  ],
  "auraSpecialRules": [
    {
      "name": "Precision Shooter Aura",
      "keywords": ["Precision Shooter Aura"]
    }
  ],
  "armySpells": [
    {
      "name": "Surge of Power",
      "cost": 1,
      "keywords": ["Surge of Power"]
    }
  ],
  "units": [
    {
      "name": "Kemba Brute Boss",
      "size": 1,
      "cost": 135,
      "page": 0,
      "uniqueHero": false,
      "quality": "3+",
      "defense": "3+",
      "tough": "6",
      "specialRules": ["Bestial", "Hero", "Tough(6)"],
      "weapons": [
        {
          "name": "Heavy Hand Weapon",
          "range": "-",
          "attacks": "A6",
          "ap": "2",
          "special": "-"
        }
      ],
      "upgrades": [
        {
          "type": "Replace Heavy Hand Weapon",
          "options": [
            {
              "name": "Flameforged Great Weapon",
              "details": "A6, Shred",
              "cost": "+10pts"
            }
          ]
        }
      ]
    }
  ]
}
```

## Notes importantes

### Les descriptions peuvent être absentes

Après traduction, certaines entrées de règles et de sorts conservent :

- `name`
- `keywords`

mais plus de champ `description`.

C'est normal : le générateur PDF peut reconstruire la description depuis le dictionnaire à partir de `keywords`.

### Certaines chaînes peuvent rester en anglais

Le JSON peut contenir un mélange de :

- texte traduit
- texte source non traduit

si une entrée est absente du dictionnaire.

### Les champs ne sont pas un schéma strict versionné

Le format suit le pipeline actuel du projet. Si Army Forge ou les scripts évoluent, certains champs peuvent être enrichis ou modifiés.

## Référence pratique

Pour voir un exemple réel généré dans ce repo :

[`generated/aof-beastmen-3.5.2.json`](./generated/aof-beastmen-3.5.2.json)
