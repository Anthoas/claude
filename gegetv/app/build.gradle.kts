import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "fr.gege.tv"
    compileSdk = 35

    defaultConfig {
        applicationId = "fr.gege.tv"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        // Source déjà prête dans l'appli (pour l'installer sur une télé sans Mac à côté) : lue dans
        // gegetv/source-preinstallee.properties (nom, serveur, identifiant, mot de passe), fichier
        // privé, jamais dans le dépôt. Sans ce fichier : aucune source préinstallée.
        val preset = Properties().apply {
            rootProject.file("source-preinstallee.properties").takeIf { it.exists() }?.reader(Charsets.UTF_8)?.use { load(it) }
        }
        fun quoted(key: String) = "\"" + preset.getProperty(key, "").replace("\\", "\\\\").replace("\"", "\\\"") + "\""
        buildConfigField("String", "PRESET_NAME", quoted("nom"))
        buildConfigField("String", "PRESET_SERVER", quoted("serveur"))
        buildConfigField("String", "PRESET_USERNAME", quoted("identifiant"))
        buildConfigField("String", "PRESET_PASSWORD", quoted("mot_de_passe"))
        // Favoris de cette source, copiés d'une autre télé (gegetv/favoris-preinstalles.json, privé).
        val favorites = rootProject.file("favoris-preinstalles.json").takeIf { it.exists() }?.readText(Charsets.UTF_8).orEmpty()
        buildConfigField("String", "PRESET_FAVORITES",
            "\"" + favorites.trim().replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n") + "\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Signée avec la clé de débogage : l'application n'est installée que sur la télé de la maison.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.tv:tv-material:1.0.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("io.coil-kt:coil-compose:2.7.0") // logos des chaînes

    val media3 = "1.5.1"
    implementation("androidx.media3:media3-exoplayer:$media3")
    implementation("androidx.media3:media3-exoplayer-hls:$media3")
    implementation("androidx.media3:media3-ui:$media3")
}
