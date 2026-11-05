plugins { kotlin("jvm") version "2.2.10"; application }
kotlin { jvmToolchain(17) }
dependencies {
    implementation("io.ktor:ktor-server-core-jvm:3.2.3")
    implementation("io.ktor:ktor-server-cio-jvm:3.2.3")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
    runtimeOnly("org.slf4j:slf4j-simple:2.0.17")
}
layout.buildDirectory.set(layout.projectDirectory.dir("../../../verification/ktor-memo/build"))
application { mainClass.set("MainKt") }
