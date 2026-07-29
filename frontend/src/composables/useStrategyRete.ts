import { ClassicPreset, NodeEditor, type GetSchemes } from 'rete'
import { AreaExtensions, AreaPlugin } from 'rete-area-plugin'
import {
    ConnectionPlugin,
    Presets as ConnectionPresets,
} from 'rete-connection-plugin'
import { Presets, VuePlugin, type VueArea2D } from 'rete-vue-plugin'
import { nextTick, ref, type Ref } from 'vue'

import {
    isStrategyValueNode,
    normalizeComparisonPort,
} from '../helpers/strategyBuilderGraph'
import type { StrategyDetail, StrategyNode } from '../types/strategyBuilder'

type ReteNode = ClassicPreset.Node
type ReteConnection = ClassicPreset.Connection<ReteNode, ReteNode>
type Schemes = GetSchemes<ReteNode, ReteConnection>
type AreaExtra = VueArea2D<Schemes>

interface StrategyReteOptions {
    host: Ref<HTMLElement | null>
    detail: Ref<StrategyDetail | null>
    selectedNodeId: Ref<string | null>
    titleForNode: (node: StrategyNode) => string
}

const RETE_FIT_SCALE = 0.98

export function useStrategyRete(options: StrategyReteOptions) {
    const ready = ref(false)
    const error = ref<string | null>(null)
    let teardown: (() => void) | null = null
    let requestedGeneration = 0
    let renderQueue = Promise.resolve()

    async function renderGraph(): Promise<void> {
        const generation = ++requestedGeneration
        const render = renderQueue.then(() => renderGeneration(generation))
        renderQueue = render.catch(() => undefined)
        return render
    }

    async function renderGeneration(generation: number): Promise<void> {
        if (generation !== requestedGeneration) {
            return
        }
        destroyActiveGraph()
        ready.value = false
        error.value = null
        const detail = options.detail.value
        if (!detail) {
            return
        }
        await nextTick()
        const host = options.host.value
        if (!host || generation !== requestedGeneration) {
            return
        }
        let localTeardown: (() => void) | null = null
        try {
            const editor = new NodeEditor<Schemes>()
            const area = new AreaPlugin<Schemes, AreaExtra>(host)
            localTeardown = () => {
                area.destroy()
                editor.clear()
            }
            const connection = new ConnectionPlugin<Schemes, AreaExtra>()
            const render = new VuePlugin<Schemes, AreaExtra>()
            const socket = new ClassicPreset.Socket('signal')
            const graphIdByReteId = new Map<string, string>()
            area.addPipe((context) => {
                if (context.type === 'nodepicked') {
                    const graphId = graphIdByReteId.get(String(context.data.id))
                    if (graphId) {
                        options.selectedNodeId.value = graphId
                    }
                }
                return context
            })
            render.addPreset(Presets.classic.setup())
            connection.addPreset(ConnectionPresets.classic.setup())
            editor.use(area)
            area.use(connection)
            area.use(render)

            const nodeMap = new Map<string, ReteNode>()
            const graphNodeById = new Map<string, StrategyNode>()
            for (const graphNode of detail.ir.nodes) {
                const reteNode = new ClassicPreset.Node(
                    options.titleForNode(graphNode),
                )
                graphNodeById.set(graphNode.id, graphNode)
                if (graphNode.type === 'comparison') {
                    reteNode.addInput(
                        'value1',
                        new ClassicPreset.Input(socket, 'value1'),
                    )
                    reteNode.addInput(
                        'value2',
                        new ClassicPreset.Input(socket, 'value2'),
                    )
                } else if (!isStrategyValueNode(graphNode)) {
                    reteNode.addInput('in', new ClassicPreset.Input(socket))
                }
                reteNode.addOutput('out', new ClassicPreset.Output(socket))
                reteNode.addControl(
                    'type',
                    new ClassicPreset.InputControl('text', {
                        initial: graphNode.type,
                        readonly: true,
                    }),
                )
                await editor.addNode(reteNode)
                await area.translate(reteNode.id, {
                    x: Number(graphNode.position?.x ?? 80),
                    y: Number(graphNode.position?.y ?? 80),
                })
                nodeMap.set(graphNode.id, reteNode)
                graphIdByReteId.set(reteNode.id, graphNode.id)
            }

            for (const graphConnection of detail.ir.connections ?? []) {
                const source = nodeMap.get(String(graphConnection.source ?? ''))
                const target = nodeMap.get(String(graphConnection.target ?? ''))
                const targetGraphNode = graphNodeById.get(
                    String(graphConnection.target ?? ''),
                )
                const requestedTargetPort = normalizeComparisonPort(
                    String(graphConnection.target_input ?? ''),
                )
                const targetPort =
                    targetGraphNode?.type === 'comparison'
                        ? requestedTargetPort === 'value2'
                            ? 'value2'
                            : 'value1'
                        : 'in'
                if (source && target) {
                    await editor.addConnection(
                        new ClassicPreset.Connection(
                            source,
                            'out',
                            target,
                            targetPort,
                        ),
                    )
                }
            }

            AreaExtensions.simpleNodesOrder(area)
            const reteNodes = editor.getNodes()
            if (reteNodes.length) {
                await AreaExtensions.zoomAt(area, reteNodes, {
                    scale: RETE_FIT_SCALE,
                })
            }
            if (generation !== requestedGeneration) {
                localTeardown()
                return
            }
            teardown = localTeardown
            localTeardown = null
            ready.value = true
        } catch (caught) {
            localTeardown?.()
            if (generation === requestedGeneration) {
                error.value =
                    caught instanceof Error
                        ? caught.message
                        : 'Rete canvas could not render.'
            }
        }
    }

    function destroyActiveGraph(): void {
        if (teardown) {
            teardown()
            teardown = null
        }
    }

    function destroy(): void {
        requestedGeneration += 1
        destroyActiveGraph()
        ready.value = false
    }

    return {
        ready,
        error,
        renderGraph,
        destroy,
    }
}
