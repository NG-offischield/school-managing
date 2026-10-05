// school_core's Android side: the local-network permission channel (Android 17).
// Same structure as maintained AGP 9 plugins: Kotlin is applied by hand when the
// app disables AGP's built-in Kotlin (android.builtInKotlin=false, Flutter template).
import com.android.Version
import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import org.jetbrains.kotlin.gradle.dsl.KotlinAndroidProjectExtension

plugins {
    id("com.android.library")
}

group = "cm.schoolmanaging.school_core"
version = "1.0"

val agpMajor = Version.ANDROID_GRADLE_PLUGIN_VERSION.substringBefore('.').toInt()
val builtInKotlin = agpMajor >= 9 && (findProperty("android.builtInKotlin")?.toString() ?: "true").toBoolean()
if (!builtInKotlin) {
    apply(plugin = "kotlin-android")
}

android {
    namespace = "cm.schoolmanaging.school_core"
    // Same SDK levels as the apps (mobile/gradle/school-android.gradle): Android 10 -> 17.
    compileSdk = 37

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        minSdk = 29
    }

    testOptions {
        unitTests.all { it.useJUnit() }
    }
}

dependencies {
    // FileProvider (DocumentOpener). minSdk 21.
    implementation("androidx.core:core:1.13.1")
    testImplementation("junit:junit:4.13.2")
}

fun configureKotlin() {
    extensions.configure(KotlinAndroidProjectExtension::class.java) {
        compilerOptions {
            jvmTarget = JvmTarget.JVM_17
        }
    }
}
if (extensions.findByName("kotlin") != null) {
    configureKotlin()
} else {
    plugins.withId("org.jetbrains.kotlin.android") { configureKotlin() }
}
