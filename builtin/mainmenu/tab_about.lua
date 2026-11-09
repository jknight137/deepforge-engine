-- Modified for Deepforge on 2026-11-09; original notices retained.
-- Luanti
-- Copyright (C) 2013 sapier
-- SPDX-License-Identifier: LGPL-2.1-or-later


local function get_renderer_info()
	local ret = {}

	-- OpenGL version, stripped to just the important part
	local s1 = core.get_active_renderer()
	if s1:sub(1, 7) == "OpenGL " then
		s1 = s1:sub(8)
	end
	local m = s1:match("^[%d.]+")
	if not m then
		m = s1:match("^ES [%d.]+")
	end
	ret[#ret+1] = m or s1
	-- video driver
	ret[#ret+1] = core.get_active_driver():lower()
	-- irrlicht device
	ret[#ret+1] = core.get_active_irrlicht_device():upper()

	return table.concat(ret, " / ")
end

return {
	name = "about",
	caption = fgettext("About"),

	cbf_formspec = function(tabview, name, tabdata)
		local logofile = defaulttexturedir .. "logo.png"
		local version = core.get_version()

		local hypertext = {
			"<tag name=heading color=#ff0>",
			"<tag name=gray color=#aaa>",
		}

		table.insert_all(hypertext, {
			"<heading>Deepforge</heading>\n",
			"Voxel engine and agentic research testbed.\n\n",
			"<heading>Capabilities</heading>\n",
			"Larger continuous worlds, persistent scripting, durable scheduling, " ..
			"and authenticated external actor control.\n\n",
			"<heading>Licensing and attribution</heading>\n",
			"Derived from Luanti. Copyright (C) 2010-2026 Perttu Ahola and contributors.\n",
			"Engine: LGPL-2.1-or-later. See COPYING.LESSER and LICENSE.txt.\n",
			"SDK: MIT. Original and dependency notices are retained in the distribution.\n",
		})

		hypertext = table.concat(hypertext)

		local fs = {
			"image[1,0.5;3.4,3.4;", core.formspec_escape(logofile), "]",
			"style_type[label;valign=center;halign=center;font=mono,bold;font_size=*1.1]",
			"label[0.1,4;5.4,0.6;",
			core.formspec_escape(version.project .. " " .. version.string), "]",
			"style_type[button_url;border=false;textcolor=#4cd9f9]",
			"button_url[1.5,4.6;2.5,0.5;homepage;Source and documentation;https://github.com/jknight137/deepforge-engine]"
		}

		if PLATFORM == "Android" then
			fs[#fs+1] = "button[0.5,5.1;4.5,0.8;share_debug;" .. fgettext("Share debug log") .. "]"
		else
			fs[#fs+1] = "tooltip[userdata;" ..
					fgettext("Opens the directory that contains user-provided worlds, games, mods,\n" ..
							"and texture packs in a file manager / explorer.") .. "]"
			fs[#fs+1] = "button[0.5,5.1;4.5,0.8;userdata;" .. fgettext("Open User Data Directory") .. "]"
		end

		local active_renderer_info = fgettext("Active renderer:") .. "\n" ..
			core.formspec_escape(get_renderer_info())
		table.insert_all(fs, {
			"style_type[textarea;valign=center;halign=center;font_size=*0.9]",
			"textarea[0.1,6;5.4,1;;", active_renderer_info, ";]",
			"hypertext[5.5,0.25;9.75,6.6;credits;", core.formspec_escape(hypertext), "]"
		})

		return table.concat(fs, "")
	end,

	cbf_button_handler = function(this, fields, name, tabdata)
		if fields.share_debug then
			local path = core.get_user_path() .. DIR_DELIM .. "debug.txt"
			core.share_file(path)
		end

		if fields.userdata then
			core.open_dir(core.get_user_path())
		end
	end,

	on_change = function(type)
		if type == "ENTER" then
			mm_game_theme.set_engine()
		end
	end,
}
