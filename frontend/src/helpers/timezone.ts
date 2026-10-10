// Function to get all available timezones using Intl API
export function getAllTimeZones() {
    const timezones = Intl.supportedValuesOf('timeZone');
    return timezones.map(tz => ({
        label: tz,
        value: tz
    }));
}