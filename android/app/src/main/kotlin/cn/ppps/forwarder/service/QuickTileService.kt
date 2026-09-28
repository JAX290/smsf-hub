package cn.ppps.forwarder.service

import android.content.Intent
import android.graphics.drawable.Icon
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import androidx.annotation.RequiresApi
import cn.ppps.forwarder.R
import cn.ppps.forwarder.activity.SplashActivity

/**
 * 快捷设置磁贴：隐藏桌面图标后，这是常规入口。
 * 下拉通知栏 -> 编辑磁贴 -> 把「收音机」拖到常用区，点一下即打开 App。
 */
@RequiresApi(Build.VERSION_CODES.N)
class QuickTileService : TileService() {

    override fun onStartListening() {
        super.onStartListening()
        qsTile?.let { t ->
            t.state = Tile.STATE_INACTIVE
            t.label = getString(R.string.app_name)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                t.icon = Icon.createWithResource(this, R.drawable.ic_forwarder)
            }
            t.updateTile()
        }
    }

    @Suppress("DEPRECATION")
    override fun onClick() {
        super.onClick()
        val intent = Intent(this, SplashActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        startActivityAndCollapse(intent)
    }
}
