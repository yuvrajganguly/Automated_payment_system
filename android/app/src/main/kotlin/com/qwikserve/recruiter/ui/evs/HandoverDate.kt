package com.qwikserve.recruiter.ui.evs

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.qwikserve.recruiter.ui.common.Chips
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.theme.Qwik
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

/**
 * "Handed over on": today unless the recruiter says otherwise.
 *
 * Vehicles often go out before anybody opens the app — a busy store morning,
 * no signal, a rider who took it the evening before — so the day can be set
 * back. Never forward: the picker refuses future days, and the server refuses
 * them again (and any day before this EV's or this rider's last return).
 *
 * Today and Yesterday are one tap because they are most of the cases; any
 * other day goes through the calendar.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HandoverDateField(date: LocalDate, onChange: (LocalDate) -> Unit, modifier: Modifier = Modifier) {
    val today = LocalDate.now()
    val yesterday = today.minusDays(1)
    var picking by remember { mutableStateOf(false) }
    val other = date != today && date != yesterday
    val label = when (date) {
        today -> "Today"
        yesterday -> "Yesterday"
        else -> shortDate(date.toString())
    }
    Column(modifier) {
        Kicker("Handed over on")
        Spacer(Modifier.height(6.dp))
        Chips(
            listOf("Today", "Yesterday", if (other) label else "Earlier…"),
            selected = label,
            onSelect = {
                when (it) {
                    "Today" -> onChange(today)
                    "Yesterday" -> onChange(yesterday)
                    else -> picking = true
                }
            },
            modifier = Modifier.horizontalScroll(rememberScrollState()),
        )
        if (date < today) {
            Spacer(Modifier.height(6.dp))
            Text(
                "Backdated to ${shortDate(date.toString())}. The office settles rent for the days before today.",
                style = MaterialTheme.typography.bodySmall,
                color = Qwik.N700,
            )
        }
    }

    if (picking) {
        // The Material picker speaks UTC midnight millis; keep it in UTC both ways
        // so the day chosen is the day sent, whatever the phone's zone.
        val todayMillis = today.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
        val state = rememberDatePickerState(
            initialSelectedDateMillis = date.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli(),
            yearRange = (today.year - 1)..today.year,
            selectableDates = object : SelectableDates {
                override fun isSelectableDate(utcTimeMillis: Long) = utcTimeMillis <= todayMillis
                override fun isSelectableYear(year: Int) = year <= today.year
            },
        )
        DatePickerDialog(
            onDismissRequest = { picking = false },
            confirmButton = {
                TextButton(
                    onClick = {
                        state.selectedDateMillis?.let {
                            onChange(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().let { d -> if (d.isAfter(today)) today else d })
                        }
                        picking = false
                    },
                ) { Text("Use this day", color = Qwik.Accent) }
            },
            dismissButton = {
                TextButton(onClick = { picking = false }) { Text("Cancel", color = Qwik.N700) }
            },
        ) {
            DatePicker(state = state, showModeToggle = false)
        }
    }
}
