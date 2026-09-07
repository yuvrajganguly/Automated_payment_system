package com.qwikserve.recruiter.data.repo

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.ExifInterface
import android.net.Uri
import android.graphics.Matrix
import com.qwikserve.recruiter.data.api.PayoutApi
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import javax.inject.Inject
import javax.inject.Singleton

/**
 * A rider's photo, from the phone to `POST /persons/{id}/documents`.
 *
 * The picture is shrunk here, not just on the server: a phone camera hands
 * back 4–6 MB and a recruiter is usually on a store's edge of a mobile
 * signal. 1 280 px at JPEG 80 is about 200 kB and still more than the
 * server's own 1 024 px profile copy needs.
 */
@Singleton
class PhotoRepository @Inject constructor(
    @ApplicationContext private val context: Context,
    private val api: PayoutApi,
) {
    suspend fun uploadPhoto(personId: Long, uri: Uri) = withContext(Dispatchers.IO) {
        val jpeg = readAndShrink(uri) ?: error("That picture could not be read.")
        val part = MultipartBody.Part.createFormData(
            "file",
            "rider-$personId.jpg",
            jpeg.toRequestBody("image/jpeg".toMediaType()),
        )
        api.uploadDocument(personId, part, "photo".toRequestBody("text/plain".toMediaType()))
    }

    private fun readAndShrink(uri: Uri): ByteArray? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        val longest = maxOf(bounds.outWidth, bounds.outHeight)
        if (longest <= 0) return null
        val opts = BitmapFactory.Options().apply {
            inSampleSize = generateSequence(1) { it * 2 }.first { longest / it <= MAX_PX * 2 }
        }
        val bitmap = context.contentResolver.openInputStream(uri)
            ?.use { BitmapFactory.decodeStream(it, null, opts) } ?: return null
        val scaled = scale(upright(bitmap, uri))
        val out = ByteArrayOutputStream()
        scaled.compress(Bitmap.CompressFormat.JPEG, QUALITY, out)
        if (!scaled.isRecycled) scaled.recycle()
        return out.toByteArray()
    }

    /** Cameras store the picture as the sensor saw it and note the turn in
     *  EXIF; without this a portrait photo of a rider arrives on its side. */
    private fun upright(bitmap: Bitmap, uri: Uri): Bitmap {
        val orientation = runCatching {
            context.contentResolver.openInputStream(uri)?.use {
                ExifInterface(it).getAttributeInt(
                    ExifInterface.TAG_ORIENTATION,
                    ExifInterface.ORIENTATION_NORMAL,
                )
            }
        }.getOrNull() ?: return bitmap
        val degrees = when (orientation) {
            ExifInterface.ORIENTATION_ROTATE_90 -> 90f
            ExifInterface.ORIENTATION_ROTATE_180 -> 180f
            ExifInterface.ORIENTATION_ROTATE_270 -> 270f
            else -> return bitmap
        }
        val turned = Bitmap.createBitmap(
            bitmap, 0, 0, bitmap.width, bitmap.height,
            Matrix().apply { postRotate(degrees) }, true,
        )
        if (turned !== bitmap) bitmap.recycle()
        return turned
    }

    private fun scale(bitmap: Bitmap): Bitmap {
        val longest = maxOf(bitmap.width, bitmap.height)
        if (longest <= MAX_PX) return bitmap
        val ratio = MAX_PX.toFloat() / longest
        return Bitmap.createScaledBitmap(
            bitmap,
            (bitmap.width * ratio).toInt().coerceAtLeast(1),
            (bitmap.height * ratio).toInt().coerceAtLeast(1),
            true,
        )
    }

    private companion object {
        const val MAX_PX = 1_280
        const val QUALITY = 80
    }
}
