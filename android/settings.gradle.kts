pluginManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories { google(); mavenCentral() }
}
rootProject.name = "NorvaneVPN"
include(":app")

// Optional OpenVPN engine: the ics-openvpn git submodule (see scripts/setup-openvpn-engine.sh).
// Without it the app still builds, but connecting reports "engine not installed" (it never fakes a connection).
val icsMain = file("ics-openvpn/main")
if (icsMain.resolve("build.gradle").exists() || icsMain.resolve("build.gradle.kts").exists()) {
    include(":openvpn-main")
    project(":openvpn-main").projectDir = icsMain
}
