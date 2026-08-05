plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "studio.room211.diktatproba"
    compileSdk = 34

    defaultConfig {
        applicationId = "studio.room211.diktatproba"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1-proba"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}
