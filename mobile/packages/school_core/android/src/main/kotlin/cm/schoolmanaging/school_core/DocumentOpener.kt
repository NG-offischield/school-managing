package cm.schoolmanaging.school_core

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import androidx.core.content.FileProvider
import java.io.File

/**
 * Opens a document the app downloaded (official PDF: receipt, report card)
 * with whatever viewer the phone has.
 *
 * The file is copied into cache/shared/ — the ONLY folder exposed by the
 * FileProvider (res/xml/school_core_file_paths.xml) — and handed over with a
 * temporary read grant: no storage permission, nothing else of the app is
 * reachable. Works the same on API 29 -> 37 (FileProvider + ACTION_VIEW).
 */
object DocumentOpener {
    private const val FOLDER = "shared"

    fun authority(activity: Activity) = "${activity.packageName}.schoolcore.files"

    fun open(activity: Activity, path: String, mimeType: String): Boolean {
        val source = File(path)
        if (!source.isFile) return false
        val folder = File(activity.cacheDir, FOLDER).apply { mkdirs() }
        val shared = File(folder, source.name)
        source.copyTo(shared, overwrite = true)
        val uri = FileProvider.getUriForFile(activity, authority(activity), shared)
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, mimeType)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        return try {
            activity.startActivity(Intent.createChooser(intent, null))
            true
        } catch (_: ActivityNotFoundException) {
            false // no PDF viewer: the file stays saved in the app
        }
    }
}

/** Own subclass: never clashes with another library's androidx FileProvider when manifests merge. */
class SchoolCoreFileProvider : FileProvider()
