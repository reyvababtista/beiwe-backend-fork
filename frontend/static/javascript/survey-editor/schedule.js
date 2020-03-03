var days_list = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
var months_list = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];


// Return the time as an h:MM AM/PM string instead of as a number of seconds past midnight
Handlebars.registerHelper("int_to_time", int_to_time);


Handlebars.registerHelper("rel_sched_to_label", function(schedule) {
    [intervention_id, days, time] = schedule;
    var label = "";
    if (days > 0) {
        label += days + " days after ";
    } else if (days < 0) {
        label += Math.abs(days) + " days before ";
    } else {
        label += " Day of ";
    }
    label += interventions[intervention_id] + " at " + int_to_time(time);
    return label;
});

// Takes a schedule of form [year, month, day, time] and returns the time as a
// string of the form "Month Day, Year at h:MM AM/PM"
Handlebars.registerHelper("abs_sched_to_label", function(schedule) {
    [year, month, day, time] = schedule;
    var label = months_list[month] + day + ", " + year + " " + int_to_time(time);

    return label;
});

// Return the time as an h:MM AM/PM string instead of as a number of seconds past midnight
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

// Return the time as a number of seconds past midnight instead of as an h:MM AM/PM string
function parse_time_string(time_string) {
    var hours = parseInt(time_string.split(':')[0]);
    if (hours == 12) {
        hours = 0;
    }
    var minutes = parseInt(time_string.split(':')[1]);
    var am_pm = time_string.split(' ')[1];
    var number_of_seconds = (hours * 3600) + (minutes * 60);
    if (am_pm == 'PM') {
        number_of_seconds += (12 * 3600);
    }
    return number_of_seconds;
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
    var number_of_seconds = parse_time_string(time_string);

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

    var datalist = {schedules: survey_times['schedule']};
    var htmlSchedule = template(datalist);
    $('#surveySchedule').html(htmlSchedule)
}


function add_relative_time() {
    var time_string = $('#new_time_timepicker').val();
    var number_of_seconds = parse_time_string(time_string);

    var num_days = $('#num_days_picker').val();
    // before_after_select can be one of 1, 0, -1
    var signed_days = num_days * $('before_after_select').val();
    var intervention_id = $('intervention_select').val();

    add_time_to_relative_timings(intervention_id, signed_days, number_of_seconds);

    renderRelativeSchedule();
}

// adds new schedule to timings, then sorts them on intervention_id, then day, then time of day
function add_time_to_relative_timings(intervention_id, days, time) {
    survey_times['schedule'].push([intervention_id, days, time]);
    survey_times['schedule'].sort(function (a, b) {
        if (a[0] === b[0]) { // if intervention_ids are the same
            if (a[1] === b[1]) { // if days are the same
                return a[2] - b[2]; // sort on time
            }
            return a[1] - b[1];
        }
        return a[0] - b[0];
    })
}


function renderAbsoluteSchedule() {
    var source = $("#absolute-schedule-template").html();
    var template = Handlebars.compile(source);

    var datalist = {schedules: survey_times['schedule']};
    var htmlSchedule = template(datalist);
    $('#surveySchedule').html(htmlSchedule)
}


function add_absolute_time() {
    var time_string = $('#new_time_timepicker').val();
    var number_of_seconds = parse_time_string(time_string);

    // TODO parse date_picker

}

// adds new schedule to timings, then sorts them chronologically
function add_time_to_absolute_timings(schedule) {
    survey_times['schedule'].push(schedule);
    survey_times['schedule'].sort(function (a, b) {
        if (a[0] === b[0]) { // if years are the same
            if (a[1] === b[1]) { // if months are the same
                if (a[2] === b[2]) { // if days are the same
                    return a[3] - b[3]; // sort on time
                }
                return a[2] - b[2];
            }
            return a[1] - b[1];
        }
        return a[0] - b[0];
    })
}


function delete_weekly_time(day_index, time_index) {
    survey_times[day_index].splice(time_index, 1);
    renderWeeklySchedule();
}


function delete_relative_time(schedule_index) {
    survey_times['schedule'].splice(schedule_index, 1);
    renderRelativeSchedule();
}


function delete_absolute_time(schedule_index) {
    survey_times['schedule'].splice(schedule_index, 1);
    renderAbsoluteSchedule();
}


$(function () {
  $('[data-toggle="tooltip"]').tooltip()
});
