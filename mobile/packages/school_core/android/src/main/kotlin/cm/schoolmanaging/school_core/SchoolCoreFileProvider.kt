package cm.schoolmanaging.school_core

import androidx.core.content.FileProvider

/**
 * The FileProvider declared in school_core's AndroidManifest.xml (merged into
 * the four apps), used by [DocumentOpener] to hand a downloaded PDF to the
 * phone's viewer. Its own subclass, as recommended for libraries: the manifest
 * merger never confuses it with another library's `androidx…FileProvider`.
 *
 * It MUST exist: Android instantiates every declared provider when the process
 * starts, before any Flutter code. Without this class every app died at launch
 * with "ClassNotFoundException: …SchoolCoreFileProvider" (all versions until
 * 2026-10-17). Exposed folder: res/xml/school_core_file_paths.xml (cache/shared/ only).
 */
class SchoolCoreFileProvider : FileProvider()
