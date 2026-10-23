import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import StrategyInspectorPanel from '../src/components/control-center/StrategyInspectorPanel.vue'

it('edits accumulation compatibility inside the common strategy inspector', async () => {
  const wrapper = mount(StrategyInspectorPanel, {
    props: { detail: { ir: { nodes: [], connections: [] }, palette: [] } as any,
      selectedNode: null, readOnly: false, validation: { status: 'valid' },
      draftName: 'Shared strategy', draftDescription: '' },

  })
  await wrapper.get('[role=checkbox]').trigger('click')
  expect(wrapper.emitted('update-accumulation')?.[0]).toEqual(['enabled', true])
  await wrapper.setProps({ readOnly: true })
  expect(wrapper.get('[role=checkbox]').classes()).toContain('n-checkbox--disabled')
})
