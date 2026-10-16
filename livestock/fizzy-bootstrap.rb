# Run once inside the isolated Fizzy container. Secrets stay in its private storage.
identity = Identity.find_or_create_by!(email_address: "livestock@localhost.local")
account = identity.accounts.first || Account.create_with_owner(account: { name: "Buffalo Soldiers" }, owner: { name: "Livestock operator", identity: identity })
user = account.users.find_by!(role: :owner)
Current.account = account
Current.user = user
board = account.boards.find_by(name: "पशु सहायता") || account.boards.create!(name: "पशु सहायता", creator: user, all_access: true)
board.publish
column_ids = {}
{ "new" => "नए मामले", "active" => "भेंट और प्रतिक्रिया", "review" => "समीक्षा" }.each do |key, name|
  column = board.columns.find_by(name: name) || board.columns.create!(name: name)
  column_ids[key] = column.id
end
access = identity.access_tokens.find_by(description: "Livestock mirror") || identity.access_tokens.create!(description: "Livestock mirror", permission: :write)
config = { columns: column_ids, base_url: "http://127.0.0.1:8767", public_url: "http://100.82.28.38:8767", account_slug: account.slug, board_id: board.id, token: access.token, board_url: "http://100.82.28.38:8767#{account.slug}/public/boards/#{board.publication.key}", source_url: "http://127.0.0.1:8766", source_public_url: "http://100.82.28.38:8766" }
File.write("/rails/storage/livestock-config.json", JSON.pretty_generate(config), perm: 0600)
puts "Local board configured"
