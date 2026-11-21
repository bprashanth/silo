# CLI outline 

## Principles 

1. Have only one way to do each thing
2. Try and mirror popular cli syntax (kubectl, sql, git etc) theyr'e all over the internet and the 9b already understands them.
3. Ensure there are example commands and a manual page. 

## Command outlines 

### Explanations via "summarise"

_Without embeddings_

1. Literal search 
2. Rank by mentions 
3. limit 5
4. Look specifically at a few pages (3-5) that mention X most and take around 2k chars around the first mention
5. 9b write an explanation about the excerpt with citations 

_with embeddings_

1. Question turned into a vector
2. Page first chunked then stored as vector 
3. Map distance between these two and take the top N
