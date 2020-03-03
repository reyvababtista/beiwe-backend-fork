var days_list = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];


// Return the time as an h:MM AM/PM string instead of as a number of seconds past midnight
Handlebars.registerHelper("int_to_time", int_to_time);


Handlebars.registerHelper("rel_sched_to_label", function(schedule) {
    [days, time, intervention_id] = schedule;
    var label = "";
    if (days > 0) {
        label = label + days + " days after";
    } else if (days < 0) {
        label = label + Math.abs(days) + "days before";
    } else {
        label += "Day of"
    }

});

function int_to_time(number_of_seconds) {
    var time_string = "";

    // Add hours (in 12-hour time)
    var hours = Math.floor(number_of_seconds / 3600) % 12;
    if (hours == 0) {
        hours = 12;
    }
    time_string += hours + ":";

    // Add minutes
    var minutes = Math.floor((number_of_seconds % 3600) / 60);
    if (minutes < 10) {
        time_string += "0" + minutes;
    } else {
        time_string += minutes;
    };

    // Add AM/PM
    if (number_of_seconds < 3600 * 12) {
        time_string += " AM";
    } else {
        time_string += " PM";
    };

    return time_string;
}


function renderWeeklySchedule() {
    var source = $("#weekly-schedule-template").html();
    var template = Handlebars.compile(source);

    var schedule = [];
    for (var i=0; i<7; i++) {
    	day_schedule = {day_name: days_list[i], times: survey_times[i]};
    	schedule.push(day_schedule);
    };

    var dataList = {schedules: schedule};
    var htmlSchedule = template(dataList);

    $('#surveySchedule').html(htmlSchedule);
}


function add_weekly_time() {
    var time_string = $('#new_time_timepicker').val();
    var hours = parseInt(time_string.split(':')[0]);
    if (hours == 12) {
        hours = 0;
    }
    var minutes = parseInt(time_string.split(':')[1]);
    var am_pm = time_string.split(' ')[1];
    var number_of_seconds = (hours * 3600) + (minutes * 60);
    if (am_pm == 'PM') {
        number_of_seconds += (12 * 3600);
    };

    var day_index = $('#day_index_select').val();

    if (day_index == "every_day") {
        // If they selected "every_day", add this time to all 7 days
        for (var i = 0; i < 7; i++) {
            add_time_to_weekly_day_index(number_of_seconds, i);
        };
    } else {
        // Otherwise, just add this time to the selected day
        add_time_to_weekly_day_index(number_of_seconds, day_index);
    };

    // Re-render the schedule
    renderWeeklySchedule();
}


function add_time_to_weekly_day_index(time, day_index) {
    // TODO change this to commented block
    survey_times[day_index].push(time);
    survey_times[day_index].sort();
    // survey_times['schedule'][day_index].push(time);
    // survey_times['schedule'][day_index].sort();
}


function renderRelativeSchedule() {
    var source = $("#relative-schedule-template").html();
    var template = Handlebars.compile(source);

    var schedule = survey_times['schedule'].map()

}


function add_relative_time() {
    var time_string = $('#new_time_timepicker').val();
    var hours = parseInt(time_string.split(':')[0]);
    if (hours == 12) {
        hours = 0;
    }
    var minutes = parseInt(time_string.split(':')[1]);
    var am_pm = time_string.split(' ')[1];
    var number_of_seconds = (hours * 3600) + (minutes * 60);
    if (am_pm == 'PM') {
        number_of_seconds += (12 * 3600);
    };

    var num_days = $('#num_days_picker').val();
    // before_after_select can be one of 1, 0, -1
    var signed_days = num_days * $('before_after_select').val();
    var intervention_id = $('intervention_select').val();

    add_time_to_relative_timings(intervention_id, signed_days, number_of_seconds);

    renderRelativeSchedule()
}


function add_time_to_relative_timings(intervention_id, days, time) {
    survey_times['schedule'].push([intervention_id, days, time])
    survey_times['schedule'].sort(function (a, b) {
        if (a[0] === b[0]) {
            if (a[1] === b[1]) {
                return a[2] - b[2]
            }
            return a[1] - b[1]
        }
        return a[0] - b[0]
    })
}


function add_time_to_absolute_timings(time) {
    survey_times['schedule'].push(time)
    survey_times['schedule'].sort(function (a, b) {
        if (a[0] === b[0]) {
            if (a[1] === b[1]) {
                if (a[2] === b[2]) {
                    return a[3] - b[3]
                }
                return a[2] - b[2]
            }
            return a[1] - b[1]
        }
        return a[0] - b[0]
    })
}


function delete_time(day_index, time_index) {
    survey_times[day_index].splice(time_index, 1);
    renderWeeklySchedule();
}

$(function () {
  $('[data-toggle="tooltip"]').tooltip()
})
