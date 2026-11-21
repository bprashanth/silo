# Mapper 

## Menu

The mapper is sent a menu at runtime. This menu describes the available fields and views. It uses this to decide on which args to use in the idli cli when the question is out of context for the mini. Eg

```
Resources and fields:
- mail: one row per email (...). Fields: id, thread_id, ..., 
direction, from_addr, subject, is_bulk, is_calendar_notice, ...
- events: one row per calendar event (about 60 days back and 60 
ahead). Fields: id, start, end, title,
location, organizer, my_response, guests, description, ...
title is one of: 'Field visit', 'Funder call', 'Tiger census 
Views: declined_with: guests of meetings I declined
Today is Friday 2026-11-20, time zone Asia/Kolkata. All data is from
my own account (87profligate@gmail.com) 
```
This comes from  either one of 
1. Whoever built the connector, like builder claude or a dev - needs to be fleshed out 
2. Sandbox claude when it created the mini and defined a materizlied view. 

The problem with this menu is it grows with the number of files, and the 9b has a fixed window for context. 

The alternative is a round trip: the mapper first runs list sheets, sees the result (a continue round), then writes the real command. That works but the 9B uses it badly.

