package fr.subtrad.tv.ui

import android.util.Log
import androidx.media3.common.Format
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.DecoderReuseEvaluation
import androidx.media3.exoplayer.analytics.AnalyticsListener

/**
 * Journal de lecture (adb logcat -s SubtradTV) : décodeurs, format, images sautées, attentes de
 * chargement. Sert à comprendre une lecture saccadée. N'écrit jamais l'adresse du flux.
 */
@UnstableApi
class PlaybackLog : AnalyticsListener {
    private var dropped = 0L
    private var rebuffers = 0

    override fun onVideoDecoderInitialized(
        eventTime: AnalyticsListener.EventTime, decoderName: String,
        initializedTimestampMs: Long, initializationDurationMs: Long,
    ) = log("décodeur vidéo : $decoderName")

    override fun onAudioDecoderInitialized(
        eventTime: AnalyticsListener.EventTime, decoderName: String,
        initializedTimestampMs: Long, initializationDurationMs: Long,
    ) = log("décodeur audio : $decoderName")

    override fun onVideoInputFormatChanged(
        eventTime: AnalyticsListener.EventTime, format: Format, decoderReuseEvaluation: DecoderReuseEvaluation?,
    ) = log("vidéo : ${format.sampleMimeType} ${format.codecs} ${format.width}x${format.height} " +
            "@${format.frameRate} i/s, ${format.bitrate / 1000} kbit/s, couleurs ${format.colorInfo}")

    override fun onAudioInputFormatChanged(
        eventTime: AnalyticsListener.EventTime, format: Format, decoderReuseEvaluation: DecoderReuseEvaluation?,
    ) = log("audio : ${format.sampleMimeType} ${format.channelCount} canaux, langue ${format.language}")

    override fun onDroppedVideoFrames(eventTime: AnalyticsListener.EventTime, droppedFrames: Int, elapsedMs: Long) {
        dropped += droppedFrames
        log("images sautées : +$droppedFrames en ${elapsedMs} ms (total $dropped) à ${eventTime.currentPlaybackPositionMs / 1000} s")
    }

    override fun onPlaybackStateChanged(eventTime: AnalyticsListener.EventTime, state: Int) {
        if (state == Player.STATE_BUFFERING && eventTime.currentPlaybackPositionMs > 0) rebuffers++
        val name = when (state) {
            Player.STATE_BUFFERING -> "chargement (attente n° $rebuffers)"
            Player.STATE_READY -> "lecture"
            Player.STATE_ENDED -> "fin"
            else -> "arrêt"
        }
        log("état : $name à ${eventTime.currentPlaybackPositionMs / 1000} s")
    }

    override fun onVideoFrameProcessingOffset(eventTime: AnalyticsListener.EventTime, totalProcessingOffsetUs: Long, frameCount: Int) =
        log("retard moyen de décodage : ${totalProcessingOffsetUs / frameCount.coerceAtLeast(1) / 1000} ms sur $frameCount images")

    override fun onBandwidthEstimate(eventTime: AnalyticsListener.EventTime, totalLoadTimeMs: Int, totalBytesLoaded: Long, bitrateEstimate: Long) {
        if (totalLoadTimeMs > 0) log("débit réseau estimé : ${bitrateEstimate / 1_000_000} Mbit/s")
    }

    private fun log(message: String) {
        Log.i("SubtradTV", message)
    }
}
