package cm.schoolmanaging.school_core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalNetworkPolicyTest {
    @Test
    fun notRequestedOnAndroid10To16() {
        for (sdk in 29..36) assertFalse("API $sdk must rely on INTERNET only", LocalNetworkPolicy.required(sdk))
    }

    @Test
    fun requestedFromAndroid17() {
        assertTrue(LocalNetworkPolicy.required(37))
        assertTrue(LocalNetworkPolicy.required(38))
    }

    @Test
    fun permissionName() {
        assertEquals("android.permission.ACCESS_LOCAL_NETWORK", LocalNetworkPolicy.PERMISSION)
    }
}
