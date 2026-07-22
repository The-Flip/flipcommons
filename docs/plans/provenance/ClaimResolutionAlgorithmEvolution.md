# Claim Resolution Algorithm Evolution

Here's the sysetm I want.

## Example

Imagine the Godzilla model has a disputed year of production:

```text
Godzilla
    year
        2012
            Alice
                cite 1
                cite 2
                cite 3
            Bob
                cite 4
                cite 1 <- points at same CitationInstance as Alice cite 1

        2013
            Charlie
                cite 5
            Dave
                cite 6
                cite 7
                cite 8
```

### Resolution

Which value, 2012 or 2013, gets displayed in the primary browsing UI?

Right now, resolution is simplistic:

- All actors have a priority. Higher-priority actors win.
- All humans have a higher priority than all current ingestion sources.
- All humans have the same priority, so the most recent human claim wins.

However, resolution will get more sophisticated. Maybe the number of people. Maybe the number of citation instances, or citation instance edges, or unique citation root sources. Maybe senior editors get more weight.

### How this maps to claims

Godzilla/year/2012/Alice is a Claim. Alice can only assert one value for Godzilla/year.

The value tier (2012 vs 2013) is NOT a stored thing; it's a GROUP BY value over the active claims for Godzilla/year.
