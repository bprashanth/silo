# Ideas to improve whatsapp search 

1. was there a "time" column that confused the model, meaning did it
   think 1130 from the timestamp was the time of the meeting because
it was stored in a time field - and if so, should that bbe renamed to
`message_timstamp` or soemthing?

2. does it make sense for all the idli commands to work on
   "converstaions" instead of messages in whatsapp? meaning then,
what were saying is that at sync time we figre out some way to group
messges into sessions or converstaions, and all the operations work
on a converstaion - we embed convos, we list convos etc. To see a
message in a convo is like to see a page in a doc.  OR, 

3. the alternative is to add a general flag to idli like --context 5
   meaning include 5 before and 5 after - that would work the same
way for mails calendar etc (though it may not make too much sense for
mails) - this would work like grep -c. 

4. Should we let clef judge whether neighboring messages are relevant
   rather than assuming they are? we could do this at sync time too
if we go the converstaion route, or if we go the -c route then Once a
message is found, deterministically retrieve: Its quoted parent.
Direct replies to it. The sender's immediately following messages.
Nearby messages within the same group. Associated attachments,
captions and URLs -- this effectively is the conversation. 
5. should we move entity resolution into code?  can we? there is the
   idea to use @ chips to identify users - but the problem is there
is no guidance unlike whatsapp which gives an autocomplete as the
user types. Is sthere anyway to show a ui assist for chips in signal?
otherwise no one will remember or even do it properly. But ideally we
would solve the group name issue (jam buns -> jam buns @ t4gc)
outside the llm alltogether. Basically before a whatsapp search we
can do determintic entity resolution fuzzy match even if there are no
chips? 
6. should we run parallel searchs across source? or a cheap
   cross-source probe for hit-counts? when a question doesn't
obvoiusly name a source run a hit-count on duckdb across mail, cal,
files and wa first so the mapper sees wa: 4 calendar: 0 -> or just
run parallel searchs. 
7. should we judge more? basically three strategies:: search then
   judge, semantic retrieval then judge, judge all within a
restricted scope. That way, both search and semantic are just ways to
restrict scope but so is a query like "last week" or "yesterday".

