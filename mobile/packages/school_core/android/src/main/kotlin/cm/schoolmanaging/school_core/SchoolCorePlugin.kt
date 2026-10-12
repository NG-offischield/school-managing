package cm.schoolmanaging.school_core

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.PluginRegistry

/**
 * Android side of school_core: the local-network permission of Android 17.
 *
 * Apps targeting API 37 need the runtime permission ACCESS_LOCAL_NETWORK
 * (group NEARBY_DEVICES) to open a TCP connection to a private address — the
 * PC that runs Django on the school's Wi-Fi. Without it the connection simply
 * times out. On Android 10–16 (API 29–36) INTERNET is enough: nothing is
 * requested there, and no API 37 symbol is ever touched (string constant +
 * SDK_INT check only).
 *
 * Channel "school_core/local_network":
 *   status       -> {sdkInt, required, granted, canAsk}
 *   request      -> same map, after the system dialog (API 37+ only)
 *   openSettings -> opens the app's settings (permission denied for good)
 *   openDocument -> {path, mimeType}: shows a downloaded official PDF (receipt, report card)
 *                   with the device's viewer; false when none is installed (DocumentOpener)
 *   clearSharedDocuments -> deletes cache/shared/ (copies handed to viewers): server switch
 *   pickImage    -> {bytes, name} | {error} | null (cancelled): system photo picker (ImagePicker)
 */
class SchoolCorePlugin :
    FlutterPlugin,
    ActivityAware,
    MethodChannel.MethodCallHandler,
    PluginRegistry.RequestPermissionsResultListener,
    PluginRegistry.ActivityResultListener {
    private var channel: MethodChannel? = null
    private var context: Context? = null
    private var binding: ActivityPluginBinding? = null
    private var pending: MethodChannel.Result? = null
    private var pendingImage: MethodChannel.Result? = null
    private var askedThisRun = false

    override fun onAttachedToEngine(flutter: FlutterPlugin.FlutterPluginBinding) {
        context = flutter.applicationContext
        channel = MethodChannel(flutter.binaryMessenger, CHANNEL).also { it.setMethodCallHandler(this) }
    }

    override fun onDetachedFromEngine(flutter: FlutterPlugin.FlutterPluginBinding) {
        channel?.setMethodCallHandler(null)
        channel = null
        context = null
    }

    override fun onAttachedToActivity(activity: ActivityPluginBinding) {
        binding = activity.also {
            it.addRequestPermissionsResultListener(this)
            it.addActivityResultListener(this)
        }
    }

    override fun onDetachedFromActivityForConfigChanges() = onDetachedFromActivity()

    override fun onReattachedToActivityForConfigChanges(activity: ActivityPluginBinding) = onAttachedToActivity(activity)

    override fun onDetachedFromActivity() {
        binding?.removeRequestPermissionsResultListener(this)
        binding?.removeActivityResultListener(this)
        binding = null
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        val activity = binding?.activity
        when (call.method) {
            "status" -> result.success(status(activity, Build.VERSION.SDK_INT))
            "request" -> request(activity, result)
            "openSettings" -> {
                if (activity == null) return result.success(false)
                activity.startActivity(
                    Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", activity.packageName, null)),
                )
                result.success(true)
            }
            "openDocument" -> {
                val path = call.argument<String>("path")
                val mime = call.argument<String>("mimeType") ?: "application/pdf"
                result.success(activity != null && path != null && DocumentOpener.open(activity, path, mime))
            }
            "clearSharedDocuments" -> result.success(context?.let { DocumentOpener.clear(it) } ?: false)
            "pickImage" -> {
                if (activity == null) return result.success(null)
                if (pendingImage != null) return result.error("BUSY", "An image is already being chosen.", null)
                pendingImage = result
                activity.startActivityForResult(ImagePicker.intent(), ImagePicker.REQUEST_CODE)
            }
            else -> result.notImplemented()
        }
    }

    private fun request(activity: Activity?, result: MethodChannel.Result) {
        val sdk = Build.VERSION.SDK_INT
        if (activity == null || !LocalNetworkPolicy.required(sdk) || granted(activity)) {
            return result.success(status(activity, sdk))
        }
        if (pending != null) return result.error("BUSY", "A permission request is already running.", null)
        pending = result
        askedThisRun = true
        activity.requestPermissions(arrayOf(LocalNetworkPolicy.PERMISSION), REQUEST_CODE)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?): Boolean {
        if (requestCode != ImagePicker.REQUEST_CODE) return false
        val result = pendingImage ?: return true
        pendingImage = null
        val activity = binding?.activity
        result.success(if (activity == null) null else ImagePicker.read(activity, resultCode, data))
        return true
    }

    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, grants: IntArray): Boolean {
        if (code != REQUEST_CODE) return false
        val result = pending ?: return true
        pending = null
        result.success(status(binding?.activity, Build.VERSION.SDK_INT))
        return true
    }

    private fun granted(activity: Activity): Boolean =
        activity.checkSelfPermission(LocalNetworkPolicy.PERMISSION) == PackageManager.PERMISSION_GRANTED

    private fun status(activity: Activity?, sdk: Int): Map<String, Any> {
        val required = LocalNetworkPolicy.required(sdk)
        val granted = !required || (activity != null && granted(activity))
        // The rationale flag is false both before the first request and once the user refused
        // for good: after one request in this run, "false" means only the app settings can grant it.
        val canAsk = required && !granted && activity != null &&
            (activity.shouldShowRequestPermissionRationale(LocalNetworkPolicy.PERMISSION) || !askedThisRun)
        return mapOf("sdkInt" to sdk, "required" to required, "granted" to granted, "canAsk" to canAsk)
    }

    companion object {
        const val CHANNEL = "school_core/local_network"
        private const val REQUEST_CODE = 0x5C01
    }
}

/** Pure version rules, unit-tested on the JVM (no device needed). */
object LocalNetworkPolicy {
    /** The ACCESS_LOCAL_NETWORK permission, added in API 37 (kept as a string: safe on API 29). */
    const val PERMISSION = "android.permission.ACCESS_LOCAL_NETWORK"

    /** First API level that enforces local network protection for apps targeting it. */
    const val SINCE_SDK = 37

    fun required(sdkInt: Int): Boolean = sdkInt >= SINCE_SDK
}
