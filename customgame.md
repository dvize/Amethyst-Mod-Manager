# Adding a Custom Game

If a game is not in the list of supported games, it may be possible to add it as a custom game. Custom games are saved as a `.json` file in Amethyst's config folder and can be shared with others.

To add a custom game, click the **+** button in the top-left corner, then click **Define Custom Game** in the bottom-left of the Add Game window.

<img width="180" height="35" alt="Define Custom Game button" src="https://github.com/user-attachments/assets/d316cfb1-2b42-4491-a573-406ada9a83ff" />

Most properties used by officially supported games can be configured here. The only limitation is that custom deployment logic cannot be defined, as that would require scripting.

---

## Options

### Game Name

The name that will appear for the game in the manager.

---

### Executable Filename

The path to the game's launch executable, relative to the game's root folder.

- Most games have their executable in the root folder — e.g. `SkyrimSELauncher.exe`
- Some games have it in a subfolder — e.g. Baldur's Gate 3 uses `bin/bg3.exe`

---

### Deploy Method

Controls how mod files are placed into the game directory. There are three options:

| Method | Description |
|--------|-------------|
| **Standard** | Mods are deployed into a single target folder (set via **Mod Sub Folder**). Use this for games like Skyrim where all mod files go into `Data`. |
| **Root** | Mods can be deployed into multiple folders within the game's root directory. Use this for games like Cyberpunk 2077, where mods can go into `bin`, `r6`, `archive`, `red4ext`, or `engine`. |
| **UE5** | For Unreal Engine 5 games. Uses custom rules to automatically route each file to the correct location, including `.utoc` files. |

---

### Mod Sub Folder

The folder, relative to the game's root, where mods should be deployed. This does not apply to the **Root** deploy method.

- Skyrim: `Data`
- Subnautica: `BepInEx/Plugins`
- Hogwarts Legacy (UE5): `Phoenix`

---

### Steam App ID

Used to detect the Proton prefix and enable the Proton Tools window for Steam-installed games. The App ID can be found on [steamdb.info](https://steamdb.info).

---

### Nexus Mods Domain

The game's identifier on Nexus Mods. This is visible in the URL when viewing the game's page on Nexus — e.g. `skyrimspecialedition`.

---

### Banner Image

The image displayed in the Add Game interface. Game banners and icons can be found on [SteamGridDB](https://www.steamgriddb.com).

---

## Advanced Options

These options control how a mod's internal folder structure is handled during installation.

For example: if a Skyrim mod is packaged with a `Data` folder included, placing it directly into Skyrim's `Data` folder would cause it to not work. The advanced options allow Amethyst to automatically strip or remap these folders so mods install correctly without manual intervention.

There are a few options we can use to do this, They can be combined but always happen in a set order.

### Strip Prefixes

Comma separated folder names. Our example above can be solved by simply adding Data into this box. If the top level folder of an installed mod is Data, it will be removed and added to the target location correctly. 

We can also add more than 1 folder, For example we could set it to BepInEx,Plugins and now if a mod ships Bepinex/plugins/content . Both the bepinex and plugins folders will be removed and only the content will be shown in the manager. If the mod ships as plugins/content it would also work. This way we add all the content to the plugins folder and not have to worry about how the author has packed their mod

### Conflict Ignore Filenames

This tells the manager to ignore certain files for that game when it comes to conflicts. If every mod for example shipped with a meta.xml file, every mod would show a conflict. In this case we would add meta.xml into this box and it will be ignored when the manager detects conflicts

### Required Top Level folders

Some games will have common top level folder names. An example of this is Cyberpunk where mods will more often than not, ship with one of the top level folders being one of "bin", "r6", "archive", "red4ext","engine". This tells the manager if the top level folder of the mod being installed is not one of these that something is wrong and needs to be fixed.

### Auto strip until required

This only applies if something is set in Required Top Level folders. The installer will keep removing top level folders until it finds one that matches. In our cyberpunk example if a mod author for some reason shipped their mod as `<author name>/<mod name>/red4ext/<content>` then this setting would remove `<author name>/<mod name>` from the mod, just leaving `red4ext/<content>`

### Strip prefixes (post install)

Strip prefixes is applied before Auto strip until required. We sometimes need to apply Strip prefixes after instead. For example Resident Evil Requiem has reframework as its Required Top Level folders but we dont need reframework in the file path. So setting it to reframework would remove it. We cant add reframework to the first Strip prefixes property because some mods ship as `<mod name>/reframework` so it wouldn't work. This method solves that issue by making sure reframework is the top level folder and them removing it so we are just left with the content

### Prepend Prefixes

The opposite of strip prefixes, this is rarely needed but whatever is set here will be added to the filepath. If we enter Plugins into this box our output would become `plugins/<content>`. If we entered BepInEx/plugins our output would become `BepInEx/Plugins/<content>`.

### Heroic App Names

This is like steam app id but for the heroic launcher, Theres no easy way to find this other than installing the game on heroic and going into the game page's settings

### Restore before deploy

This will almost always never needs to be disabled (Mewgenics is the only case where this needs to be disabled). When we hit deploy on the manager it will run restore first to clean the game folder before it applys the new mod list. This disables that feature.

### Wine DLL Overrides

You can set wine dll overrides here for a game that might need them. For example a BepInEx game will need the winhttp override. When we deploy this override is applied to the prefix

## Example

Lets use **Mount & Blade II: Bannerlord as an example**. I'll leave all the obvious stuff out

Exe name - **bin/Win64_Shipping_Client/Bannerlord.Native.exe** - This can also be found on [steamdb.info](https://steamdb.info) but checking in the games files is usually easier/more reliable

Deploy method - **Standard** - The mods just go into 1 folder so we just need standard

Mod sub-folder - **Modules** - Modules is in the root of the game folder and this is where the mods go

Strip prefixes - **Modules** - Some mods ship with the modules folder already attached, we dont want this so this removes it

And thats all we need for this game

---

## Example 2

Lets do **Clair Obscur: Expedition 33** this time

Exe name - **Expedition33_Steam.exe**

Deploy method - **Ue5** - the game uses the ue5 folder structure

Game sub-folder - **Sandfall** - This folder is in the game root and is where the mods will go

Strip prefixes - **Sandfall** - Just in case a mod author ships their mod with sandfall as a top level folder, it gets removed.

Thats it for this game too, It's similar to the first just a differnt deploy method

---

## Example 3

Lets do **Cyberpunk 2077** . Even though this is in the manager by default this is how we would add it here

Exe name - **Cyberpunk2077.exe**

Deploy method - **Root** - This games mods are shipped to be placed straight into the root folder

Required Top Level folders - **bin , r6 , archive , red4ext , engine** - Mods often ship with at least one of these

Auto strip until required - **Enabled** - No harm in enabling this, it should be used when Required Top Level folders is set.

Thats it for this game, In the event a mod author does not ship their mod with one of the required top level folders, there's a dialogue window that appears to manually fix it, theres not much we can do to automatically fix it.

---

## Example 4

**Resident Evil Requiem** - Also officially supported but a little different to other examples

Exe name - **re9.exe**

Deploy method **Standard** - Mod again just go into 1 folder

Mod Sub Folder - **reframework** - The folder mods go into

Required Top Level folders - **reframework** - Some mods ship as `<modname>/reframework`, this removes `<modname>` from the filepath

Auto strip until required - **Enabled**

Strip prefixes (post install) - **reframework** - Since we have set reframework as the mod sub folder, we dont need this as a prefix so this removes it if it is present.

Conflict Ignore Filenames - **modinfo.ini,readme.txt** - Most mods ship with these which will cause every mod to show conflicts. This makes the manager ignore them 

Wine DLL Overrides **dinput8=native,builtin** - reframework requires this dll override

---

## Output

The output of a custom added game is in the home/user/.config/AmethystModManager/Customgames folder in json format. You can share this with anyone and all they need to do is place this in that folder.

---

## Limitations

Some games require custom scrpting to handle their deploy logic. Baldurs gate 3 for example needs an entire util to handle modsettings.lsx. We wouldn't be able to add this sort of game as a custom game and it would need it own unqiue handler.
Games like The sims 4 and also Baldurs gate 3 where mods are added somewhere in the prefix also currently wont work, as we can't define that just yet although it is rare for a games mods to be installed this way. This might change in future.





