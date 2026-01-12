export function timezoneOffset() {
    return Math.abs(new Date().getTimezoneOffset())
}

export function convertTime(date, offset) {
    if (offset) {
        offset = Math.floor(offset * 2 / 60);
    } else {
        offset = 0;
    }

    date.setHours(date.getHours() + (date.getTimezoneOffset() / 60) + offset);
    date.setMinutes(date.getMinutes() + (date.getTimezoneOffset() / 60) + offset % 1 * 60);
    return date;
}

// Function to get all available timezones using Intl API
export function getAllTimeZones() {
    const timezones = Intl.supportedValuesOf('timeZone');
    return timezones.map(tz => ({
        label: tz,
        value: tz
    }));
}