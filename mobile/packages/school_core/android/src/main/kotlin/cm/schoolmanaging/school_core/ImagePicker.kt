package cm.schoolmanaging.school_core

import android.app.Activity
import android.content.Intent
import android.os.Build
import android.provider.MediaStore

/**
 * Lets the user choose ONE image (profile photo) with the system picker:
 * Android Photo Picker (MediaStore.ACTION_PICK_IMAGES, API 33+) or
 * ACTION_GET_CONTENT on API 29-32. No storage permission: the app only gets
 * a temporary read grant on the chosen file, whose bytes are read once.
 * The server checks the real content (people/photos.py).
 */
object ImagePicker {
    const val REQUEST_CODE = 0x5C02

    /** Larger files are not read into memory (the server refuses > 3 MB anyway). */
    const val MAX_BYTES = 3 * 1024 * 1024

    fun intent(): Intent =
        if (Build.VERSION.SDK_INT >= 33) {
            Intent(MediaStore.ACTION_PICK_IMAGES).setType("image/*")
        } else {
            Intent(Intent.ACTION_GET_CONTENT).setType("image/*").addCategory(Intent.CATEGORY_OPENABLE)
        }

    /** {bytes, name} of the chosen image, {error: "too_large" | "unreadable"}, or null if cancelled. */
    fun read(activity: Activity, resultCode: Int, data: Intent?): Map<String, Any>? {
        if (resultCode != Activity.RESULT_OK) return null
        val uri = data?.data ?: return null
        return try {
            activity.contentResolver.openInputStream(uri)?.use { input ->
                val buffer = input.readNBytesCompat(MAX_BYTES + 1)
                if (buffer.size > MAX_BYTES) mapOf("error" to "too_large") else mapOf("bytes" to buffer, "name" to "photo")
            } ?: mapOf("error" to "unreadable")
        } catch (_: Exception) {
            mapOf("error" to "unreadable")
        }
    }

    private fun java.io.InputStream.readNBytesCompat(limit: Int): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        val chunk = ByteArray(64 * 1024)
        while (out.size() < limit) {
            val read = read(chunk, 0, minOf(chunk.size, limit - out.size()))
            if (read < 0) break
            out.write(chunk, 0, read)
        }
        return out.toByteArray()
    }
}
