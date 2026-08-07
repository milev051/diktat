plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "studio.room211.diktat"
    compileSdk = 34

    defaultConfig {
        applicationId = "studio.room211.diktat"
        minSdk = 26
        targetSdk = 34
        versionCode = 46
        versionName = "1.33"
    }

    buildTypes {
        release {
            // Bez ovoga Material biblioteka nadme APK sa 0.8 na 6.4 MB.
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // Potpisuje se debug kljucem: aplikacija se ionako samo sideload-uje.
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

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    testImplementation("junit:junit:4.13.2")
}
