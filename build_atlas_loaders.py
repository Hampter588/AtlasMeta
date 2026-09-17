#!/usr/bin/env python3
"""Build Atlas metadata for Fabric-family legacy loaders."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


OUTPUT = Path("_site/v1")
USER_AGENT = "AtlasMeta/1.0 (+https://github.com/Hampter588/AtlasMeta)"
EPOCH = "1970-01-01T00:00:00.000Z"

SOURCES = (
    {
        "uid": "org.legacyfabric.fabric-loader",
        "name": "Legacy Fabric Loader",
        "base": "https://meta.legacyfabric.net/v2/",
        "game": "versions/game",
        "loaders": "versions/loader/{game}",
        "profile": "versions/loader/{game}/{loader}/profile/json",
    },
    {
        "uid": "org.babric.fabric-loader",
        "name": "Babric Loader",
        "base": "https://meta.babric.glass-launcher.net/v2/",
        "game": "versions/game",
        "loaders": "versions/loader/{game}",
        "profile": "versions/loader/{game}/{loader}/profile/json",
    },
    {
        "uid": "net.ornithemc.loader",
        "name": "Ornithe Loader",
        "base": "https://meta.ornithemc.net/v3/",
        "game": "versions/game",
        "loaders": "versions/fabric-loader/{game}",
        "profile": "versions/fabric-loader/{game}/{loader}/profile/json",
    },
)

STATIC_PACKAGES = (
    {
        "uid": "io.github.rift",
        "name": "Rift Loader",
        "versions": ({
            "version": "1.0.4-106",
            "releaseTime": "2019-01-01T07:33:38.000Z",
            "type": "release",
            "requires": [{"uid": "net.minecraft", "equals": "1.13"}],
            "compatibleJavaMajors": [8],
            "mainClass": "net.minecraft.launchwrapper.Launch",
            "+tweakers": ["org.dimdev.riftloader.launch.RiftLoaderClientTweaker"],
            "libraries": [
                {
                    "name": "org.dimdev:rift:1.0.4-106",
                    "MMC-absoluteUrl": "https://github.com/DimensionalDevelopment/Rift/releases/download/v1.0.4-106/Rift-1.0.4-106.jar",
                },
                {
                    "name": "org.dimdev:mixin:0.7.11-SNAPSHOT",
                    "downloads": {"artifact": {
                        "url": "https://github.com/skjsjhb/lost-libraries/releases/download/1.0/mixin-0.7.11-evil.jar",
                        "sha1": "64f9be9dcab3fec97fe4d571f5a602ede704ff49",
                    }},
                },
                {"name": "org.ow2.asm:asm:6.2", "url": "https://repo1.maven.org/maven2/"},
                {"name": "org.ow2.asm:asm-commons:6.2", "url": "https://repo1.maven.org/maven2/"},
                {"name": "org.ow2.asm:asm-tree:6.2", "url": "https://repo1.maven.org/maven2/"},
                {"name": "net.minecraft:launchwrapper:1.12"},
            ],
        },),
    },
    {
        "uid": "com.unascribed.nilloader",
        "name": "NilLoader",
        "versions": ({
            "version": "1.4.0",
            "releaseTime": "2026-08-06T00:00:28.000Z",
            "type": "release",
            "+agents": [{"name": "com.unascribed:nilloader:1.4.0", "url": "https://repo.sleeping.town"}],
        },),
    },
    {
        "uid": "net.xiaoyu233.fml",
        "name": "FishModLoader / MITE",
        "versions": ({
            "version": "3.4.4",
            "releaseTime": "2026-08-23T07:26:47.000Z",
            "type": "release",
            "requires": [{"uid": "net.minecraft", "equals": "1.6.4"}],
            "compatibleJavaMajors": [8],
            "mainClass": "net.xiaoyu233.fml.relaunch.client.Main",
            "mainJar": {
                "name": "net.xiaoyu233.fishmodloader:mite-fml:3.4.4",
                "MMC-absoluteUrl": "https://github.com/MinecraftIsTooEasy/FishModLoader/releases/download/3.4.4/1.6.4-MITE-HDS_FMLv3.4.4.jar",
            },
        },),
    },
)


def fetch_json(url: str):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=45) as response:
        return loads(response.read())


def endpoint(source, template: str, **values) -> str:
    encoded = {key: quote(value, safe="") for key, value in values.items()}
    return source["base"] + template.format(**encoded)


def build_profile(source, game):
    game_version = game["version"]
    if game.get("environment") not in (None, "*", "client"):
        return None

    loaders = fetch_json(endpoint(source, source["loaders"], game=game_version))
    selected = next((item for item in loaders if item["loader"].get("stable", True)), None)
    if selected is None and loaders:
        selected = loaders[0]
    if selected is None:
        return None

    loader_version = selected["loader"]["version"]
    profile = fetch_json(endpoint(source, source["profile"], game=game_version, loader=loader_version))
    version = f"{loader_version}+mc.{game_version}"
    arguments = profile.get("arguments") or {}
    jvm_args = [arg for arg in arguments.get("jvm", ()) if isinstance(arg, str)]
    game_args = [arg for arg in arguments.get("game", ()) if isinstance(arg, str)]

    component = {
        "uid": source["uid"],
        "name": source["name"],
        "formatVersion": 1,
        "version": version,
        "releaseTime": EPOCH,
        "type": "release",
        "requires": [{"uid": "net.minecraft", "equals": game_version}],
        "compatibleJavaMajors": [8],
        "mainClass": profile["mainClass"],
        "libraries": profile.get("libraries", []),
    }
    if jvm_args:
        component["+jvmArgs"] = jvm_args
    if profile.get("minecraftArguments"):
        component["minecraftArguments"] = profile["minecraftArguments"]
    elif game_args:
        component["minecraftArguments"] = " ".join(game_args)

    return component


def write_package(source):
    games = fetch_json(source["base"] + source["game"])
    components = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(build_profile, source, game) for game in games]
        for future in as_completed(futures):
            try:
                component = future.result()
            except Exception as error:
                print(f"warning: {source['name']} profile skipped: {error}")
                continue
            if component:
                components.append(component)

    components.sort(key=lambda item: item["version"], reverse=True)
    package_dir = OUTPUT / source["uid"]
    package_dir.mkdir(parents=True, exist_ok=True)
    index_versions = []

    for component in components:
        contents = dumps(component, indent=2, ensure_ascii=False)
        (package_dir / f"{component['version']}.json").write_text(contents, encoding="utf-8")
        index_versions.append({
            "version": component["version"],
            "type": component["type"],
            "releaseTime": component["releaseTime"],
            "requires": component["requires"],
            "recommended": True,
            "sha256": sha256(contents.encode()).hexdigest(),
        })

    package = {
        "uid": source["uid"],
        "name": source["name"],
        "formatVersion": 1,
        "versions": index_versions,
    }
    package_contents = dumps(package, indent=2, ensure_ascii=False)
    (package_dir / "index.json").write_text(package_contents, encoding="utf-8")
    print(f"Built {len(components)} {source['name']} profiles")
    return {"uid": source["uid"], "name": source["name"], "sha256": sha256(package_contents.encode()).hexdigest()}


def write_static_package(package):
    package_dir = OUTPUT / package["uid"]
    package_dir.mkdir(parents=True, exist_ok=True)
    index_versions = []
    for values in package["versions"]:
        component = {"uid": package["uid"], "name": package["name"], "formatVersion": 1, **values}
        contents = dumps(component, indent=2, ensure_ascii=False)
        (package_dir / f"{component['version']}.json").write_text(contents, encoding="utf-8")
        index_version = {
            key: component[key]
            for key in ("version", "type", "releaseTime", "requires")
            if key in component
        }
        index_version["recommended"] = True
        index_version["sha256"] = sha256(contents.encode()).hexdigest()
        index_versions.append(index_version)

    index = {
        "uid": package["uid"],
        "name": package["name"],
        "formatVersion": 1,
        "versions": index_versions,
    }
    contents = dumps(index, indent=2, ensure_ascii=False)
    (package_dir / "index.json").write_text(contents, encoding="utf-8")
    print(f"Built {len(index_versions)} {package['name']} profiles")
    return {"uid": package["uid"], "name": package["name"], "sha256": sha256(contents.encode()).hexdigest()}


def main():
    package_refs = [write_package(source) for source in SOURCES]
    package_refs.extend(write_static_package(package) for package in STATIC_PACKAGES)
    root_path = OUTPUT / "index.json"
    root = loads(root_path.read_text(encoding="utf-8"))
    new_uids = {package["uid"] for package in package_refs}
    root["packages"] = [package for package in root["packages"] if package["uid"] not in new_uids]
    root["packages"].extend(package_refs)
    root["packages"].sort(key=lambda package: package["uid"])
    root_path.write_text(dumps(root, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
