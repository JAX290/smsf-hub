package cn.ppps.forwarder.workers

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.google.gson.Gson
import cn.ppps.forwarder.core.Core
import cn.ppps.forwarder.entity.result.SendResponse
import cn.ppps.forwarder.utils.Log
import cn.ppps.forwarder.utils.Worker
import com.xuexiang.xutil.data.DateUtils
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Locale

class UpdateLogsWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            val sendResponseJson = inputData.getString(Worker.UPDATE_LOGS)
            Log.d("UpdateLogsWorker", "UpdateLogsWorker sendResponseJson: $sendResponseJson")
            val sendResponse = Gson().fromJson(sendResponseJson, SendResponse::class.java)
            if (sendResponse.logId == 0L) {
                Log.e("UpdateLogsWorker", "UpdateLogsWorker error: logId is 0")
                return@withContext Result.failure()
            }
            if (sendResponse.status >= 0) {
                // 【v61 数据精简】存进手机数据库的响应文本截断，别把整段正文/长报文留下
                val raw = sendResponse.response ?: ""
                val brief = if (raw.length > 500) raw.substring(0, 500) + "…（已截断）" else raw
                val response = brief + "\nAt " + DateUtils.getNowString(SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()))
                Thread.sleep(100) //让status=-1的日志先更新
                Core.logs.updateStatus(sendResponse.logId, sendResponse.status, response)
            } else {
                val raw = sendResponse.response ?: ""
                val brief = if (raw.length > 300) raw.substring(0, 300) + "…" else raw
                Core.logs.updateResponse(sendResponse.logId, brief)
            }

            return@withContext Result.success()
        } catch (e: Exception) {
            e.printStackTrace()
            Log.e("UpdateLogsWorker", "UpdateLogsWorker error: ${e.message}")
            return@withContext Result.failure()
        }
    }

}